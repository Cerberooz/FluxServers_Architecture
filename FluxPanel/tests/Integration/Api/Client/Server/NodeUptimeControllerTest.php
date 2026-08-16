<?php

namespace Pterodactyl\Tests\Integration\Api\Client\Server;

use Pterodactyl\Tests\Integration\Api\Client\ClientApiIntegrationTestCase;

class NodeUptimeControllerTest extends ClientApiIntegrationTestCase
{
    public function testOwnerSeesRecentUptimeReportedByTheirNode(): void
    {
        [$user, $server] = $this->generateTestAccount();
        $server->node->forceFill([
            'uptime_seconds' => 12345,
            'uptime_reported_at' => now(),
        ])->save();

        $this->actingAs($user)->getJson($this->link($server, '/node-uptime'))
            ->assertOk()
            ->assertJsonPath('uptime', 12345);
    }
}
