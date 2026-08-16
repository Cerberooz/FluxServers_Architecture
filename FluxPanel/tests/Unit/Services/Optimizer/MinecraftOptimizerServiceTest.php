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
}
