<?php

namespace Pterodactyl\Tests\Integration\Api\Client\Server;

use Pterodactyl\Models\ServerOptimizerRun;
use Pterodactyl\Tests\Integration\Api\Client\ClientApiIntegrationTestCase;

class OptimizerControllerTest extends ClientApiIntegrationTestCase
{
    public function testOptimizerKeepsOnlyTheTenNewestPerformanceReportsPerServer(): void
    {
        [$user, $server] = $this->generateTestAccount();

        foreach (range(1, 12) as $number) {
            $server->optimizerRuns()->create([
                'type' => 'automatic_resource_alert',
                'status' => 'failed',
                'automatic' => true,
                'summary' => ['message' => "Alert {$number}"],
                'error' => 'Spark did not publish a report URL.',
                'started_at' => now(),
                'completed_at' => now(),
            ]);
        }

        // Loading the report API also cleans up history made before the
        // retention policy was introduced.
        $this->actingAs($user)->getJson($this->link($server, '/optimizer?page=1'))
            ->assertOk()
            ->assertJsonPath('meta.pagination.total', 10);

        $this->assertSame(10, ServerOptimizerRun::query()
            ->where('server_id', $server->id)
            ->where('type', '!=', 'configuration_scan')
            ->count());
    }

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
            ->assertOk()
            ->assertJsonPath('meta.unread', 5);

        $this->assertNotNull($run->fresh()->read_at);
    }

    public function testOwnerCanIgnoreAConfigurationFindingBoundThroughItsRun(): void
    {
        [$user, $server] = $this->generateTestAccount();
        $run = $server->optimizerRuns()->create([
            'type' => 'configuration_scan',
            'status' => 'completed',
            'started_at' => now(),
            'completed_at' => now(),
        ]);
        $finding = $run->findings()->create([
            'rule_id' => 'view-distance',
            'severity' => 'medium',
            'title' => 'High view distance',
            'explanation' => 'Test finding.',
            'gameplay_change' => true,
            'restart_required' => true,
            'evidence' => ['observed' => '16'],
            'recommendation' => ['file' => 'server.properties', 'key' => 'view-distance', 'value' => 8],
        ]);

        $this->actingAs($user)->postJson($this->link($server, "/optimizer/findings/{$finding->id}/ignore"))
            ->assertNoContent();

        $this->assertTrue($finding->fresh()->ignored);
    }
}
