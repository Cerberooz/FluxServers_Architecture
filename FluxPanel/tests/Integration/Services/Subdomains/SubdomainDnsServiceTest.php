<?php

namespace Pterodactyl\Tests\Integration\Services\Subdomains;

use Pterodactyl\Models\ServerSubdomain;
use Pterodactyl\Models\SubdomainDomain;
use Pterodactyl\Services\Servers\PublicMinecraftAddressService;
use Pterodactyl\Services\Subdomains\DNSProvider;
use Pterodactyl\Services\Subdomains\SubdomainDnsService;
use Pterodactyl\Tests\Integration\IntegrationTestCase;

class SubdomainDnsServiceTest extends IntegrationTestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        config()->set('pterodactyl.minecraft_public_host', 'play.fluxservers.cloud');
    }

    public function testItCreatesOnlyTheProtectedMinecraftSrvRecord(): void
    {
        $server = $this->createServerModel();
        $server->allocation->update(['ip' => '203.0.113.10', 'port' => 25566]);
        $domain = $this->domain();

        $provider = \Mockery::mock(DNSProvider::class);
        $provider->shouldReceive('findRecord')->once()->with('zone-123', 'SRV', '_minecraft._tcp.play.fluxmc.net')->andReturnNull();
        $provider->shouldReceive('createRecord')->once()->with('zone-123', \Mockery::on(fn (array $record) => $record === [
            'type' => 'SRV',
            'name' => '_minecraft._tcp.play.fluxmc.net',
            'data' => ['service' => '_minecraft', 'proto' => '_tcp', 'name' => 'play.fluxmc.net', 'priority' => 0, 'weight' => 0, 'port' => 25566, 'target' => 'play.fluxservers.cloud'],
            'ttl' => 1,
        ]))->andReturn(['id' => 'srv-record']);

        $service = $this->service($provider);
        $subdomain = $service->create($server, $domain, 'Play');
        $service->sync($subdomain);

        $subdomain->refresh();
        $this->assertSame(ServerSubdomain::STATUS_ACTIVE, $subdomain->status);
        $this->assertSame('srv-record', $subdomain->srv_record_id);
        $this->assertNull($subdomain->a_record_id);
        $this->assertNull($subdomain->target_ip);
        $this->assertSame(25566, $subdomain->target_port);
        $this->assertSame('play.fluxservers.cloud:25566', app(PublicMinecraftAddressService::class)->address($server->allocation));
    }

    public function testItUpdatesTheSrvPortAfterAnAllocationChange(): void
    {
        $server = $this->createServerModel();
        $server->allocation->update(['port' => 4217]);
        $subdomain = $this->service(\Mockery::mock(DNSProvider::class))->create($server, $this->domain(), 'james');
        $subdomain->update(['srv_record_id' => 'stale-record']);
        $provider = \Mockery::mock(DNSProvider::class);
        $provider->shouldReceive('findRecord')->once()->andReturn([
            'id' => 'srv-record', 'type' => 'SRV', 'name' => '_minecraft._tcp.james.fluxmc.net',
            'data' => ['priority' => 0, 'weight' => 0, 'port' => 3333, 'target' => 'play.fluxservers.cloud'],
        ]);
        $provider->shouldReceive('updateRecord')->once()->with('zone-123', 'srv-record', \Mockery::on(fn (array $record) => $record['data']['port'] === 4217))->andReturn(['id' => 'srv-record']);

        $this->service($provider)->sync($subdomain);
        $this->assertDatabaseHas('server_subdomains', ['id' => $subdomain->id, 'target_port' => 4217, 'srv_record_id' => 'srv-record']);
    }

    public function testItRenamesTheStoredSrvRecordInsteadOfCreatingAnOrphan(): void
    {
        $server = $this->createServerModel();
        $domain = $this->domain();
        $subdomain = $this->service(\Mockery::mock(DNSProvider::class))->create($server, $domain, 'james');
        $subdomain->update(['srv_record_id' => 'old-srv-record']);
        $renamed = $this->service(\Mockery::mock(DNSProvider::class))->rename($subdomain, 'survival');

        $provider = \Mockery::mock(DNSProvider::class);
        $provider->shouldReceive('findRecord')->once()->with('zone-123', 'SRV', '_minecraft._tcp.survival.fluxmc.net')->andReturnNull();
        $provider->shouldReceive('updateRecord')->once()->with('zone-123', 'old-srv-record', \Mockery::on(fn (array $record) => $record['name'] === '_minecraft._tcp.survival.fluxmc.net'))->andReturn(['id' => 'old-srv-record']);
        $provider->shouldNotReceive('createRecord');

        $this->service($provider)->sync($renamed);
        $this->assertDatabaseHas('server_subdomains', ['id' => $subdomain->id, 'hostname' => 'survival.fluxmc.net', 'srv_record_id' => 'old-srv-record']);
    }

    public function testItDoesNotWriteDnsWhenTheSrvRecordAlreadyMatches(): void
    {
        $server = $this->createServerModel();
        $server->allocation->update(['port' => 4217]);
        $subdomain = $this->service(\Mockery::mock(DNSProvider::class))->create($server, $this->domain(), 'james');
        $provider = \Mockery::mock(DNSProvider::class);
        $provider->shouldReceive('findRecord')->once()->andReturn([
            'id' => 'srv-record', 'type' => 'SRV', 'name' => '_minecraft._tcp.james.fluxmc.net',
            'data' => ['priority' => 0, 'weight' => 0, 'port' => 4217, 'target' => 'play.fluxservers.cloud'],
        ]);
        $provider->shouldNotReceive('createRecord');
        $provider->shouldNotReceive('updateRecord');

        $this->service($provider)->sync($subdomain);
        $this->assertDatabaseHas('server_subdomains', ['id' => $subdomain->id, 'srv_record_id' => 'srv-record', 'status' => ServerSubdomain::STATUS_ACTIVE]);
    }

    public function testItRejectsReservedLabels(): void
    {
        $service = $this->service(\Mockery::mock(DNSProvider::class));
        $this->expectExceptionMessage('That subdomain label is reserved.');
        $service->create($this->createServerModel(), $this->domain(['reserved_labels' => ['custom']]), 'play');
    }

    public function testItRejectsDuplicateHostnamesAndAllowsRenameAtTheLimit(): void
    {
        $domain = $this->domain(['max_per_server' => 1]);
        $service = $this->service(\Mockery::mock(DNSProvider::class));
        $subdomain = $service->create($this->createServerModel(), $domain, 'community');
        $this->assertSame('new-community.fluxmc.net', $service->rename($subdomain, 'New-Community')->hostname);

        $this->expectExceptionMessage('That hostname is already in use.');
        $service->create($this->createServerModel(), $domain, 'new-community');
    }

    private function service(DNSProvider $provider): SubdomainDnsService
    {
        return new SubdomainDnsService($provider, app(PublicMinecraftAddressService::class));
    }

    private function domain(array $attributes = []): SubdomainDomain
    {
        return SubdomainDomain::query()->create(array_merge([
            'domain' => 'fluxmc.net',
            'provider_zone_id' => 'zone-123',
            'max_per_server' => 2,
        ], $attributes));
    }
}
