<?php

namespace Pterodactyl\Tests\Integration\Api\Client\Server;

use Illuminate\Support\Facades\Bus;
use Pterodactyl\Jobs\Subdomains\SyncServerSubdomainJob;
use Pterodactyl\Models\ServerSubdomain;
use Pterodactyl\Models\SubdomainDomain;
use Pterodactyl\Tests\Integration\Api\Client\ClientApiIntegrationTestCase;

class SubdomainControllerTest extends ClientApiIntegrationTestCase
{
    public function testOwnerCanCreateListAndRenameASubdomain(): void
    {
        Bus::fake();
        [$user, $server] = $this->generateTestAccount();
        $domain = SubdomainDomain::query()->create([
            'domain' => 'fluxmc.net',
            'provider_zone_id' => 'zone-123',
            'max_per_server' => 1,
        ]);

        $response = $this->actingAs($user)->postJson($this->link($server, '/subdomains'), [
            'domain_id' => $domain->id,
            'label' => 'Play',
        ]);

        $response->assertStatus(202)->assertJsonPath('attributes.hostname', 'play.fluxmc.net');
        Bus::assertDispatched(SyncServerSubdomainJob::class);

        $subdomain = ServerSubdomain::query()->firstOrFail();
        $this->actingAs($user)->getJson($this->link($server, '/subdomains'))
            ->assertOk()
            ->assertJsonPath('data.0.hostname', 'play.fluxmc.net');

        $this->actingAs($user)->patchJson($this->link($server, '/subdomains/' . $subdomain->id), ['label' => 'Community'])
            ->assertStatus(202)
            ->assertJsonPath('attributes.hostname', 'community.fluxmc.net');

        $this->assertDatabaseHas('server_subdomains', ['id' => $subdomain->id, 'hostname' => 'community.fluxmc.net']);
    }

    public function testCustomerCannotModifyAnotherServersSubdomain(): void
    {
        [$user, $server] = $this->generateTestAccount();
        [, $otherServer] = $this->generateTestAccount();
        $domain = SubdomainDomain::query()->create(['domain' => 'fluxmc.net', 'provider_zone_id' => 'zone-123']);
        $subdomain = ServerSubdomain::query()->create([
            'server_id' => $otherServer->id,
            'domain_id' => $domain->id,
            'label' => 'private',
            'hostname' => 'private.fluxmc.net',
        ]);

        $this->actingAs($user)->patchJson($this->link($server, '/subdomains/' . $subdomain->id), ['label' => 'stolen'])
            ->assertForbidden();
    }
}
