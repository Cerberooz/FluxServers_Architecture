<?php

namespace Pterodactyl\Tests\Integration\Services\Subdomains;

use Pterodactyl\Models\ServerSubdomain;
use Pterodactyl\Models\SubdomainDomain;
use Pterodactyl\Services\Subdomains\DNSProvider;
use Pterodactyl\Services\Subdomains\SubdomainDnsService;
use Pterodactyl\Tests\Integration\IntegrationTestCase;

class SubdomainDnsServiceTest extends IntegrationTestCase
{
    public function testItCreatesMinecraftAAndSrvRecordsAndAllowsRenameAtTheLimit(): void
    {
        $server = $this->createServerModel();
        $server->allocation->update(['ip' => '203.0.113.10', 'port' => 25566]);
        $domain = SubdomainDomain::query()->create([
            'domain' => 'fluxmc.net',
            'provider_zone_id' => 'zone-123',
            'max_per_server' => 1,
        ]);

        $provider = \Mockery::mock(DNSProvider::class);
        $provider->shouldReceive('createRecord')->once()->with('zone-123', \Mockery::on(fn (array $record) => $record['type'] === 'A' && $record['name'] === 'play.fluxmc.net' && $record['content'] === '203.0.113.10'))->andReturn(['id' => 'a-record']);
        $provider->shouldReceive('createRecord')->once()->with('zone-123', \Mockery::on(fn (array $record) => $record['type'] === 'SRV' && $record['name'] === '_minecraft._tcp.play.fluxmc.net' && $record['data']['port'] === 25566))->andReturn(['id' => 'srv-record']);

        $service = new SubdomainDnsService($provider);
        $subdomain = $service->create($server, $domain, 'Play');
        $service->sync($subdomain);

        $subdomain->refresh();
        $this->assertSame(ServerSubdomain::STATUS_ACTIVE, $subdomain->status);
        $this->assertSame('a-record', $subdomain->a_record_id);
        $this->assertSame('srv-record', $subdomain->srv_record_id);
        $this->assertSame('203.0.113.10', $subdomain->target_ip);
        $this->assertSame(25566, $subdomain->target_port);

        $renamed = $service->rename($subdomain, 'New-Play');
        $this->assertSame('new-play.fluxmc.net', $renamed->hostname);
    }

    public function testItRejectsReservedLabels(): void
    {
        $server = $this->createServerModel();
        $domain = SubdomainDomain::query()->create([
            'domain' => 'fluxmc.net',
            'provider_zone_id' => 'zone-123',
            'reserved_labels' => ['www'],
            'max_per_server' => 2,
        ]);
        $service = new SubdomainDnsService(\Mockery::mock(DNSProvider::class));

        $this->expectExceptionMessage('That subdomain label is reserved.');
        $service->create($server, $domain, 'www');
    }

    public function testItRejectsDuplicateHostnames(): void
    {
        $domain = SubdomainDomain::query()->create([
            'domain' => 'fluxmc.net',
            'provider_zone_id' => 'zone-123',
            'max_per_server' => 2,
        ]);
        $service = new SubdomainDnsService(\Mockery::mock(DNSProvider::class));
        $service->create($this->createServerModel(), $domain, 'play');

        $this->expectExceptionMessage('That hostname is already in use.');
        $service->create($this->createServerModel(), $domain, 'play');
    }
}
