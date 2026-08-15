<?php

namespace Pterodactyl\Services\Subdomains;

use Illuminate\Support\Str;
use Pterodactyl\Exceptions\DisplayException;
use Pterodactyl\Models\Allocation;
use Pterodactyl\Models\Server;
use Pterodactyl\Models\ServerSubdomain;
use Pterodactyl\Models\SubdomainDnsOperation;
use Pterodactyl\Models\SubdomainDomain;
use Pterodactyl\Services\Servers\PublicMinecraftAddressService;

class SubdomainDnsService
{
    private const RESERVED_LABELS = [
        'www', 'api', 'panel', 'admin', 'billing', 'status', 'mail', 'smtp', 'ftp', 'sftp',
        'node', 'nodes', 'play', 'minecraft', 'mc', 'support', 'cdn', 'assets', 'static',
        'db', 'database', 'mysql', 'redis', 'auth',
    ];

    public function __construct(
        private DNSProvider $provider,
        private PublicMinecraftAddressService $publicAddress,
    ) {
    }

    public function validateLabel(string $label): string
    {
        $label = Str::lower(trim($label));
        if (!preg_match('/^(?!-)[a-z0-9-]{1,63}(?<!-)$/', $label)) {
            throw new DisplayException('Use a valid lowercase DNS label.');
        }

        return $label;
    }

    public function create(Server $server, SubdomainDomain $domain, string $label): ServerSubdomain
    {
        $label = $this->validateLabel($label);
        $this->assertEligible($server, $domain, $label);

        return ServerSubdomain::query()->create([
            'server_id' => $server->id,
            'domain_id' => $domain->id,
            'label' => $label,
            'hostname' => "{$label}.{$domain->domain}",
            'status' => ServerSubdomain::STATUS_PENDING,
        ]);
    }

    public function rename(ServerSubdomain $subdomain, string $label): ServerSubdomain
    {
        $label = $this->validateLabel($label);
        $subdomain->loadMissing('server.allocation', 'domain');
        $this->assertEligible($subdomain->server, $subdomain->domain, $label, $subdomain->id);

        $subdomain->forceFill([
            'label' => $label,
            'hostname' => "{$label}.{$subdomain->domain->domain}",
            'status' => ServerSubdomain::STATUS_UPDATING,
            'last_error' => null,
        ])->save();

        return $subdomain;
    }

    /**
     * Synchronize the one managed Minecraft SRV record. The origin allocation
     * remains internal: all customer domains point to the protected hostname.
     */
    public function sync(ServerSubdomain $subdomain): void
    {
        $subdomain->loadMissing('server.allocation', 'domain');
        $allocation = $subdomain->server->allocation;
        if (!$allocation || !$this->validPort($allocation)) {
            throw new DisplayException('This server does not have a valid primary allocation.');
        }

        $subdomain->forceFill(['status' => ServerSubdomain::STATUS_UPDATING, 'last_error' => null])->save();
        $expected = $this->srvRecord($subdomain, $allocation);

        try {
            // Legacy versions created an A record to the node IP. Its stored ID
            // makes it safe to remove without touching unrelated zone records.
            if ($subdomain->a_record_id) {
                $this->provider->deleteRecord($subdomain->domain->provider_zone_id, $subdomain->a_record_id);
                $subdomain->forceFill(['a_record_id' => null, 'target_ip' => null])->save();
            }

            $actual = $this->provider->findRecord(
                $subdomain->domain->provider_zone_id,
                'SRV',
                $expected['name'],
            );

            if ($actual && $this->matchesExpectedSrv($actual, $expected)) {
                $recordId = $actual['id'];
            } elseif ($actual) {
                $recordId = $this->provider->updateRecord(
                    $subdomain->domain->provider_zone_id,
                    $actual['id'],
                    $expected,
                )['id'];
            } elseif ($subdomain->srv_record_id) {
                // A rename changes the record name, so it cannot be found by
                // the new name yet. Updating the managed ID moves that record
                // in place and avoids leaving the old hostname behind.
                $recordId = $this->provider->updateRecord(
                    $subdomain->domain->provider_zone_id,
                    $subdomain->srv_record_id,
                    $expected,
                )['id'];
            } else {
                $recordId = $this->provider->createRecord(
                    $subdomain->domain->provider_zone_id,
                    $expected,
                )['id'];
            }

            $subdomain->forceFill([
                'status' => ServerSubdomain::STATUS_ACTIVE,
                'allocation_id' => $allocation->id,
                'target_ip' => null,
                'target_port' => $allocation->port,
                'a_record_id' => null,
                'srv_record_id' => $recordId,
                'last_error' => null,
                'last_synced_at' => now(),
            ])->save();
            $this->operation($subdomain, 'sync', 'success', null, ['port' => $allocation->port, 'target' => $this->publicAddress->host()]);
        } catch (\Throwable $exception) {
            $subdomain->forceFill(['status' => ServerSubdomain::STATUS_ERROR, 'last_error' => $this->safeMessage($exception)])->save();
            $this->operation($subdomain, 'sync', 'failed', $this->safeMessage($exception), ['port' => $allocation->port, 'target' => $this->publicAddress->host()]);
            throw $exception;
        }
    }

    public function delete(ServerSubdomain $subdomain): void
    {
        $subdomain->loadMissing('domain');

        try {
            // Both IDs are managed IDs stored by Fluid. a_record_id exists only
            // for cleaning up records made by pre-protected-ingress releases.
            if ($subdomain->srv_record_id) {
                $this->provider->deleteRecord($subdomain->domain->provider_zone_id, $subdomain->srv_record_id);
            }
            if ($subdomain->a_record_id) {
                $this->provider->deleteRecord($subdomain->domain->provider_zone_id, $subdomain->a_record_id);
            }
            $this->operation($subdomain, 'delete', 'success');
            $subdomain->delete();
        } catch (\Throwable $exception) {
            $subdomain->forceFill([
                'status' => ServerSubdomain::STATUS_DELETING,
                'last_error' => $this->safeMessage($exception),
            ])->save();
            $this->operation($subdomain, 'delete', 'failed', $this->safeMessage($exception));
            throw $exception;
        }
    }

    /** @return array<string, mixed> */
    private function srvRecord(ServerSubdomain $subdomain, Allocation $allocation): array
    {
        $target = $this->publicAddress->host();

        return [
            'type' => 'SRV',
            'name' => "_minecraft._tcp.{$subdomain->hostname}",
            'data' => [
                'service' => '_minecraft',
                'proto' => '_tcp',
                'name' => $subdomain->hostname,
                'priority' => 0,
                'weight' => 0,
                'port' => $allocation->port,
                'target' => $target,
            ],
            'ttl' => 1,
        ];
    }

    /** @param array<string, mixed> $actual @param array<string, mixed> $expected */
    private function matchesExpectedSrv(array $actual, array $expected): bool
    {
        $actualData = $actual['data'] ?? [];
        $expectedData = $expected['data'];

        return strtolower(rtrim((string) ($actual['name'] ?? ''), '.')) === strtolower($expected['name'])
            && strtolower((string) ($actual['type'] ?? '')) === 'srv'
            && (int) ($actualData['priority'] ?? -1) === $expectedData['priority']
            && (int) ($actualData['weight'] ?? -1) === $expectedData['weight']
            && (int) ($actualData['port'] ?? -1) === $expectedData['port']
            && strtolower(rtrim((string) ($actualData['target'] ?? ''), '.')) === strtolower($expectedData['target']);
    }

    private function assertEligible(Server $server, SubdomainDomain $domain, string $label, ?int $ignoreId = null): void
    {
        if (!$domain->enabled) throw new DisplayException('This domain is currently unavailable.');
        if (!$server->allocation || !$this->validPort($server->allocation)) throw new DisplayException('This server does not have a valid primary allocation.');
        $reserved = array_map('strtolower', array_merge(self::RESERVED_LABELS, $domain->reserved_labels ?? []));
        if (in_array($label, $reserved, true)) throw new DisplayException('That subdomain label is reserved.');
        if (($domain->allowed_egg_ids ?? []) && !in_array($server->egg_id, $domain->allowed_egg_ids, true)) throw new DisplayException('This game is not allowed for that domain.');
        if (ServerSubdomain::query()->where('hostname', "{$label}.{$domain->domain}")->when($ignoreId, fn ($query) => $query->whereKeyNot($ignoreId))->exists()) throw new DisplayException('That hostname is already in use.');
        if (ServerSubdomain::query()->where('server_id', $server->id)->where('domain_id', $domain->id)->when($ignoreId, fn ($query) => $query->whereKeyNot($ignoreId))->count() >= $domain->max_per_server) throw new DisplayException('This server has reached the subdomain limit for that domain.');
    }

    private function validPort(Allocation $allocation): bool
    {
        return $allocation->port >= 1 && $allocation->port <= 65535;
    }

    private function safeMessage(\Throwable $exception): string
    {
        return Str::limit($exception->getMessage(), 1000, '');
    }

    private function operation(ServerSubdomain $subdomain, string $operation, string $status, ?string $message = null, ?array $context = null): void
    {
        SubdomainDnsOperation::query()->create([
            'subdomain_id' => $subdomain->id,
            'operation' => $operation,
            'status' => $status,
            'message' => $message,
            'context' => $context,
        ]);
    }
}
