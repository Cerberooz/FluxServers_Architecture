<?php

namespace Pterodactyl\Services\Subdomains;

use Illuminate\Support\Str;
use Pterodactyl\Models\Allocation;
use Pterodactyl\Models\Server;
use Pterodactyl\Models\ServerSubdomain;
use Pterodactyl\Models\SubdomainDnsOperation;
use Pterodactyl\Models\SubdomainDomain;
use Pterodactyl\Exceptions\DisplayException;

class SubdomainDnsService
{
    public function __construct(private DNSProvider $provider) {}

    public function validateLabel(string $label): string
    {
        $label = Str::lower(trim($label));
        if (!preg_match('/^(?!-)[a-z0-9-]{1,63}(?<!-)$/', $label)) throw new DisplayException('Use a valid lowercase DNS label.');
        return $label;
    }

    public function create(Server $server, SubdomainDomain $domain, string $label): ServerSubdomain
    {
        $label = $this->validateLabel($label);
        $this->assertEligible($server, $domain, $label);
        return ServerSubdomain::query()->create(['server_id' => $server->id, 'domain_id' => $domain->id, 'label' => $label, 'hostname' => "{$label}.{$domain->domain}", 'status' => ServerSubdomain::STATUS_PENDING]);
    }

    public function rename(ServerSubdomain $subdomain, string $label): ServerSubdomain
    {
        $label = $this->validateLabel($label);
        $subdomain->loadMissing('server', 'domain');
        $this->assertEligible($subdomain->server, $subdomain->domain, $label, $subdomain->id);
        $subdomain->forceFill(['label' => $label, 'hostname' => "{$label}.{$subdomain->domain->domain}", 'status' => ServerSubdomain::STATUS_UPDATING, 'last_error' => null])->save();
        return $subdomain;
    }

    public function sync(ServerSubdomain $subdomain): void
    {
        $subdomain->loadMissing('server.allocation', 'domain');
        $allocation = $subdomain->server->allocation;
        if (!$allocation || !filter_var($allocation->ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) throw new DisplayException('This server does not have a valid IPv4 primary allocation.');
        $subdomain->forceFill(['status' => ServerSubdomain::STATUS_UPDATING, 'last_error' => null])->save();
        $createdARecordId = null;
        $createdSrvRecordId = null;
        try {
            $a = ['type' => 'A', 'name' => $subdomain->hostname, 'content' => $allocation->ip, 'ttl' => 1, 'proxied' => false];
            $aResult = $subdomain->a_record_id ? $this->provider->updateRecord($subdomain->domain->provider_zone_id, $subdomain->a_record_id, $a) : $this->provider->createRecord($subdomain->domain->provider_zone_id, $a);
            $createdARecordId = $subdomain->a_record_id ? null : $aResult['id'];
            $srvId = null;
            if ($this->isMinecraftJava($subdomain->server) && $allocation->port !== 25565) {
                $srv = ['type' => 'SRV', 'name' => "_minecraft._tcp.{$subdomain->hostname}", 'data' => ['service' => '_minecraft', 'proto' => '_tcp', 'name' => $subdomain->hostname, 'priority' => 0, 'weight' => 0, 'port' => $allocation->port, 'target' => $subdomain->hostname], 'ttl' => 1];
                $srvResult = $subdomain->srv_record_id ? $this->provider->updateRecord($subdomain->domain->provider_zone_id, $subdomain->srv_record_id, $srv) : $this->provider->createRecord($subdomain->domain->provider_zone_id, $srv);
                $srvId = $srvResult['id'];
                $createdSrvRecordId = $subdomain->srv_record_id ? null : $srvId;
            } elseif ($subdomain->srv_record_id) {
                $this->provider->deleteRecord($subdomain->domain->provider_zone_id, $subdomain->srv_record_id);
            }
            $subdomain->forceFill(['status' => ServerSubdomain::STATUS_ACTIVE, 'allocation_id' => $allocation->id, 'target_ip' => $allocation->ip, 'target_port' => $allocation->port, 'a_record_id' => $aResult['id'], 'srv_record_id' => $srvId, 'last_synced_at' => now()])->save();
            $this->operation($subdomain, 'sync', 'success');
        } catch (\Throwable $exception) {
            // Do not leave a newly-created A record behind if a later step (such as
            // the Minecraft SRV record) fails before this subdomain can be persisted.
            foreach (array_filter([$createdSrvRecordId, $createdARecordId]) as $recordId) {
                try {
                    $this->provider->deleteRecord($subdomain->domain->provider_zone_id, $recordId);
                } catch (\Throwable) {
                    // Preserve the original failure; reconciliation can repair a provider-side orphan.
                }
            }
            $subdomain->forceFill(['status' => ServerSubdomain::STATUS_ERROR, 'last_error' => $exception->getMessage()])->save();
            $this->operation($subdomain, 'sync', 'failed', $exception->getMessage());
            throw $exception;
        }
    }

    public function delete(ServerSubdomain $subdomain): void
    {
        $subdomain->loadMissing('domain');
        try {
            if ($subdomain->a_record_id) $this->provider->deleteRecord($subdomain->domain->provider_zone_id, $subdomain->a_record_id);
            if ($subdomain->srv_record_id) $this->provider->deleteRecord($subdomain->domain->provider_zone_id, $subdomain->srv_record_id);
            $this->operation($subdomain, 'delete', 'success');
            $subdomain->delete();
        } catch (\Throwable $exception) {
            $subdomain->forceFill(['status' => $subdomain->status === ServerSubdomain::STATUS_DELETING ? ServerSubdomain::STATUS_DELETING : ServerSubdomain::STATUS_ERROR, 'last_error' => $exception->getMessage()])->save();
            $this->operation($subdomain, 'delete', 'failed', $exception->getMessage());
            throw $exception;
        }
    }

    private function assertEligible(Server $server, SubdomainDomain $domain, string $label, ?int $ignoreId = null): void
    {
        if (!$domain->enabled) throw new DisplayException('This domain is currently unavailable.');
        if (in_array($label, array_map('strtolower', $domain->reserved_labels ?? []), true)) throw new DisplayException('That subdomain label is reserved.');
        if (($domain->allowed_egg_ids ?? []) && !in_array($server->egg_id, $domain->allowed_egg_ids, true)) throw new DisplayException('This game is not allowed for that domain.');
        if (ServerSubdomain::query()->where('hostname', "{$label}.{$domain->domain}")->when($ignoreId, fn ($query) => $query->whereKeyNot($ignoreId))->exists()) throw new DisplayException('That hostname is already in use.');
        if (ServerSubdomain::query()->where('server_id', $server->id)->where('domain_id', $domain->id)->when($ignoreId, fn ($query) => $query->whereKeyNot($ignoreId))->count() >= $domain->max_per_server) throw new DisplayException('This server has reached the subdomain limit for that domain.');
    }

    private function isMinecraftJava(Server $server): bool { return str_contains(Str::lower($server->nest->name ?? ''), 'minecraft') && !str_contains(Str::lower($server->nest->name ?? ''), 'bedrock'); }
    private function operation(ServerSubdomain $subdomain, string $operation, string $status, ?string $message = null): void { SubdomainDnsOperation::query()->create(['subdomain_id' => $subdomain->id, 'operation' => $operation, 'status' => $status, 'message' => $message]); }
}
