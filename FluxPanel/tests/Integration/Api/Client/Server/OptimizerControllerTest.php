<?php

namespace Pterodactyl\Tests\Integration\Api\Client\Server;

use Pterodactyl\Models\ServerOptimizerRun;
use Pterodactyl\Tests\Integration\Api\Client\ClientApiIntegrationTestCase;

class OptimizerControllerTest extends ClientApiIntegrationTestCase
{
    public function testOwnerCanPaginateAndReadAutomaticOptimizerReports(): void
    {
        [$user, $server] = $this->generateTestAccount();

        foreach (range(1, 6) as $number) {
            $server->optimizerRuns()->create([
                'type' => 'automatic_resource_alert',
                'status' => 'completed',
                'automatic' => true,
                'flagged_at' => now(),
                'summary' => ['message' => "Alert {$number}"],
                'started_at' => now(),
                'completed_at' => now(),
            ]);
        }

        $this->actingAs($user)->getJson($this->link($server, '/optimizer?page=1'))
            ->assertOk()
            ->assertJsonCount(5, 'data')
            ->assertJsonPath('meta.pagination.total', 6)
            ->assertJsonPath('meta.unread', 6);

        $run = ServerOptimizerRun::query()->where('server_id', $server->id)->latest()->firstOrFail();
        $this->actingAs($user)->postJson($this->link($server, "/optimizer/runs/{$run->id}/read"))
            ->assertOk();

        $this->assertNotNull($run->fresh()->read_at);
    }
}
