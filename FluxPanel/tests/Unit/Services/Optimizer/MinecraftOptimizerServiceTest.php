<?php

namespace Pterodactyl\Tests\Unit\Services\Optimizer;

use Pterodactyl\Exceptions\DisplayException;
use Pterodactyl\Repositories\Wings\DaemonCommandRepository;
use Pterodactyl\Repositories\Wings\DaemonFileRepository;
use Pterodactyl\Repositories\Wings\DaemonServerRepository;
use Pterodactyl\Services\Optimizer\MinecraftOptimizerService;
use Pterodactyl\Tests\TestCase;

class MinecraftOptimizerServiceTest extends TestCase
{
    public function testItOnlyAcceptsOfficialSparkReportUrls(): void
    {
        $service = new MinecraftOptimizerService(
            \Mockery::mock(DaemonFileRepository::class),
            \Mockery::mock(DaemonCommandRepository::class),
            \Mockery::mock(DaemonServerRepository::class),
        );
        $method = new \ReflectionMethod($service, 'reportId');

        $this->assertSame('AbC123', $method->invoke($service, 'https://spark.lucko.me/AbC123?raw=1'));
        $this->expectException(DisplayException::class);
        $method->invoke($service, 'https://example.com/internal-service');
    }

    public function testItSummarizesSparkHealthMetrics(): void
    {
        $service = new MinecraftOptimizerService(
            \Mockery::mock(DaemonFileRepository::class),
            \Mockery::mock(DaemonCommandRepository::class),
            \Mockery::mock(DaemonServerRepository::class),
        );
        $method = new \ReflectionMethod($service, 'summarizeReport');
        $summary = $method->invoke($service, [
            'type' => 'health',
            'metadata' => [
                'platform' => ['name' => 'Paper', 'minecraftVersion' => '1.21.1'],
                'platformStatistics' => ['tps' => ['last1m' => 19.9], 'mspt' => ['last1m' => ['median' => 31, 'percentile95' => 55]], 'memory' => ['heap' => ['used' => 100, 'max' => 200]],
            ],
            'timeWindowStatistics' => [['tps' => 18.5, 'msptMedian' => 40, 'entities' => 23]],
        ], 'abc123');

        $this->assertSame('abc123', $summary['report_id']);
        $this->assertSame(18.5, $summary['tps']);
        $this->assertSame(40, $summary['mspt_median']);
        $this->assertSame(55, $summary['mspt_p95']);
        $this->assertSame('very_healthy', $summary['server_health']['status']);
        $this->assertFalse($summary['analysis']['normal']);
    }

    public function testItPreservesNetworkEvidenceForAutomaticReports(): void
    {
        $service = new MinecraftOptimizerService(
            \Mockery::mock(DaemonFileRepository::class),
            \Mockery::mock(DaemonCommandRepository::class),
            \Mockery::mock(DaemonServerRepository::class),
        );
        $method = new \ReflectionMethod($service, 'summarizeReport');
        $summary = $method->invoke($service, ['type' => 'health', 'metadata' => []], 'abc123', [
            'network' => ['ingress_bytes_per_second' => 25 * 1024 * 1024, 'egress_bytes_per_second' => 1],
        ]);

        $this->assertSame(25 * 1024 * 1024, $summary['network']['ingress_bytes_per_second']);
    }

    public function testItScansCommonConfigurationFilesAndOffersWhitelistedProfiles(): void
    {
        $service = new MinecraftOptimizerService(
            \Mockery::mock(DaemonFileRepository::class),
            \Mockery::mock(DaemonCommandRepository::class),
            \Mockery::mock(DaemonServerRepository::class),
        );
        $server = new \Pterodactyl\Models\Server();
        $server->setRelation('egg', new \Pterodactyl\Models\Egg(['name' => 'Paper']));
        $server->setRelation('nest', new \Pterodactyl\Models\Nest(['name' => 'Minecraft']));

        $method = new \ReflectionMethod($service, 'rules');
        $rules = collect($method->invoke($service, $server, '1.21.11', [
            'server.properties' => "view-distance=16\nsimulation-distance=12\nmax-chained-neighbor-updates=1000000\n",
            'bukkit.yml' => "ticks-per:\n  autosave: 2000\n",
            'spigot.yml' => "ticks-per:\n  hopper-check: 1\n  hopper-transfer: 1\n",
            'config/paper-world-defaults.yml' => "chunks:\n  max-auto-save-chunks-per-tick: 48\nmisc:\n  redstone-implementation: VANILLA\n",
            'config/paper-global.yml' => "chunk-loading-advanced:\n  player-max-concurrent-chunk-generates: -1\n",
        ]));

        $hopper = $rules->firstWhere('rule_id', 'hopper-check');
        $this->assertSame(['Risky: 4', 'Safe: 8', 'Very Safe: 12'], array_column($hopper['recommendation']['options'], 'label'));
        $this->assertTrue($rules->contains(fn (array $rule) => $rule['rule_id'] === 'chained-neighbor-updates'));
        $this->assertTrue($rules->contains(fn (array $rule) => $rule['rule_id'] === 'redstone-implementation'));
        $this->assertSame('config/paper-world-defaults.yml', $rules->firstWhere('rule_id', 'auto-save-chunks')['recommendation']['file']);
    }

    public function testItReplacesNestedYamlConfigurationValues(): void
    {
        $service = new MinecraftOptimizerService(
            \Mockery::mock(DaemonFileRepository::class),
            \Mockery::mock(DaemonCommandRepository::class),
            \Mockery::mock(DaemonServerRepository::class),
        );
        $method = new \ReflectionMethod($service, 'replaceValue');

        $updated = $method->invoke($service, "world-settings:\n  default:\n    hopper-check: 1\n", 'world-settings.default.hopper-check', '8');

        $this->assertSame("world-settings:\n  default:\n    hopper-check: 8\n", $updated);
    }

    public function testItDetectsDocumentedEntityAndExplosionPerformanceSettings(): void
    {
        $service = new MinecraftOptimizerService(
            \Mockery::mock(DaemonFileRepository::class),
            \Mockery::mock(DaemonCommandRepository::class),
            \Mockery::mock(DaemonServerRepository::class),
        );
        $server = new \Pterodactyl\Models\Server();
        $server->setRelation('egg', new \Pterodactyl\Models\Egg(['name' => 'Paper']));
        $server->setRelation('nest', new \Pterodactyl\Models\Nest(['name' => 'Minecraft']));

        $method = new \ReflectionMethod($service, 'rules');
        $rules = collect($method->invoke($service, $server, '1.21.11', [
            'spigot.yml' => "world-settings:\n  default:\n    entity-activation-range:\n      monsters: 48\n",
            'config/paper-world-defaults.yml' => "environment:\n  optimize-explosions: false\ncollisions:\n  max-entity-collisions: 16\n",
        ]));

        $this->assertTrue($rules->contains(fn (array $rule) => $rule['rule_id'] === 'monster-activation-range'));
        $this->assertTrue($rules->contains(fn (array $rule) => $rule['rule_id'] === 'optimize-explosions'));
        $this->assertTrue($rules->contains(fn (array $rule) => $rule['rule_id'] === 'entity-collision-cap'));
    }
}
