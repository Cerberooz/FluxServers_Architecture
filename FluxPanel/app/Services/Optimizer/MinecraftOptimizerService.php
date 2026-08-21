<?php

namespace Pterodactyl\Services\Optimizer;

use Illuminate\Support\Str;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use Pterodactyl\Jobs\Optimizer\CaptureOptimizerNetworkSampleJob;
use Pterodactyl\Jobs\Optimizer\CollectSparkReportJob;
use Pterodactyl\Exceptions\DisplayException;
use Pterodactyl\Models\Server;
use Pterodactyl\Models\ServerOptimizerFinding;
use Pterodactyl\Models\ServerOptimizerRun;
use Pterodactyl\Models\ServerOptimizerSnapshot;
use Pterodactyl\Repositories\Wings\DaemonCommandRepository;
use Pterodactyl\Repositories\Wings\DaemonFileRepository;
use Pterodactyl\Repositories\Wings\DaemonServerRepository;
use Pterodactyl\Services\Plugins\ModrinthPluginService;

class MinecraftOptimizerService
{
    /**
     * The common, server-wide Minecraft configuration files. Paper 1.19+
     * stores its files below config/, while older Paper/Purpur installations
     * commonly keep them in the server root, so both layouts are supported.
     */
    private const FILES = [
        'server.properties',
        'bukkit.yml',
        'spigot.yml',
        'config/paper-global.yml',
        'config/paper-world-defaults.yml',
        'paper-global.yml',
        'paper-world-defaults.yml',
        'paper-world.yml',
        'purpur.yml',
        'pufferfish.yml',
    ];

    public function __construct(
        private DaemonFileRepository $files,
        private DaemonCommandRepository $commands,
        private DaemonServerRepository $servers,
        private ModrinthPluginService $metadata,
    ) {}

    public function scan(Server $server): ServerOptimizerRun
    {
        $run = $this->createRun($server, ['type' => 'configuration_scan', 'status' => 'running', 'started_at' => now()]);
        try {
            $runtime = $this->metadata->runtimeMetadata($server);
            $implementation = $runtime['software'] ?? ($server->egg->name . ' (' . $server->nest->name . ')');
            $configs = [];
            foreach (self::FILES as $path) {
                try { $configs[$path] = $this->files->setServer($server)->getContent($path, 524288); } catch (\Throwable) { }
            }
            $plugins = $this->listDirectory($server, '/plugins');
            $mods = $this->listDirectory($server, '/mods');
            $version = $runtime['minecraft_version'] ?? $this->detectVersion($configs['server.properties'] ?? '', $server);
            $rules = $this->rules($server, $version, $configs, $runtime['software'] ?? null);
            $actionable = collect($rules)->filter(fn (array $finding) => in_array($finding['severity'] ?? '', ['medium', 'high', 'critical'], true))->count();
            $reviews = collect($rules)->filter(fn (array $finding) => ($finding['severity'] ?? 'informational') !== 'informational')->count();
            $summary = $this->jsonSafe([
                'implementation' => $implementation,
                'minecraft_version' => $version,
                'java' => $this->detectJava($server->image),
                'memory_mb' => $server->memory,
                'cpu_percent' => $server->cpu,
                'plugins' => $plugins,
                'mods' => $mods,
                'files_scanned' => array_keys($configs),
                'spark' => $this->sparkState($server, $plugins, $mods, $version, $runtime['software'] ?? null),
                'server_health' => $this->configurationHealth($actionable),
                'analysis' => $reviews
                    ? ['normal' => false, 'conclusion' => $actionable ? 'Caution' : 'Healthy', 'message' => "Configuration scan found {$reviews} optimization setting(s) worth reviewing. Apply only recommendations that suit this server's gameplay."]
                    : ['normal' => true, 'conclusion' => 'Very Healthy', 'message' => 'Configuration scan completed normally. No performance-impacting settings were found in the checked files.'],
            ]);
            // Use a freshly-loaded model here. If a database JSON write fails,
            // Eloquent keeps the failed attributes marked as dirty on $run and
            // would otherwise also prevent the error state from being saved.
            ServerOptimizerRun::findOrFail($run->id)->update([
                'status' => 'completed',
                'summary' => $summary,
                'completed_at' => now(),
            ]);
            foreach ($rules as $finding) $run->findings()->create($finding);
        } catch (\Throwable $exception) {
            // Do not reuse $run: it can contain an invalid JSON summary from a
            // failed completion write. A direct query makes every failed scan
            // terminal and leaves its actual cause available to administrators.
            ServerOptimizerRun::query()->whereKey($run->id)->update([
                'status' => 'failed',
                'error' => Str::limit($exception->getMessage() ?: $exception::class, 65535, ''),
                'completed_at' => now(),
            ]);
            throw $exception;
        }
        return $run->fresh('findings');
    }

    public function apply(ServerOptimizerFinding $finding, mixed $selectedValue = null, bool $hasSelectedValue = false): ServerOptimizerSnapshot
    {
        $recommendation = $finding->recommendation;
        if (!$recommendation || !isset($recommendation['file'], $recommendation['key'], $recommendation['value'])) throw new DisplayException('This finding does not contain an applicable configuration recommendation.');
        $options = $recommendation['options'] ?? [];
        if (($finding->gameplay_change ?? false) && !$hasSelectedValue) throw new DisplayException('Choose one of the listed configuration profiles before applying this gameplay-affecting setting.');
        if ($hasSelectedValue) {
            $option = collect($options)->first(fn ($candidate) => is_array($candidate) && json_encode($candidate['value'] ?? null) === json_encode($selectedValue));
            if (!$option) throw new DisplayException('The selected configuration profile is not available for this finding. Scan again before applying it.');
            $selectedValue = $option['value'];
        }
        $server = $finding->run()->with('server')->firstOrFail()->server;
        if (!$server) {
            throw new DisplayException('The server for this optimizer finding no longer exists. Scan the server again.');
        }

        try {
            $path = $recommendation['file'];
            $content = $this->files->setServer($server)->getContent($path, 524288);
            $value = $hasSelectedValue ? $selectedValue : $recommendation['value'];
            $replacement = $this->replaceValue($content, $recommendation['key'], is_bool($value) ? ($value ? 'true' : 'false') : (string) $value);
            if ($replacement === $content) {
                throw new DisplayException('The expected configuration value was not found. Scan again before applying this recommendation.');
            }
            $snapshot = ServerOptimizerSnapshot::query()->create(['server_id' => $server->id, 'finding_id' => $finding->id, 'path' => $path, 'contents' => $content]);
            $this->files->setServer($server)->putContent($path, $replacement);

            return $snapshot;
        } catch (DisplayException $exception) {
            throw $exception;
        } catch (\Throwable $exception) {
            report($exception);
            throw new DisplayException('Fluid could not save this configuration through Wings. Check that the server is online and its files are writable, then try again.');
        }
    }

    public function rollback(ServerOptimizerSnapshot $snapshot): void
    {
        if ($snapshot->restored_at) throw new DisplayException('This snapshot has already been restored.');
        $this->files->setServer($snapshot->server)->putContent($snapshot->path, $snapshot->contents);
        $snapshot->update(['restored_at' => now()]);
    }

    public function startProfile(Server $server, string $mode, bool $automatic = false, array $trigger = [], bool $flagged = true): ServerOptimizerRun
    {
        $activeRuns = $server->optimizerRuns()->where('type', 'like', 'spark_%')->whereIn('status', ['queued', 'running'])->get();
        foreach ($activeRuns as $activeRun) {
            // A profile and its follow-up report collection complete in under five
            // minutes. Mark abandoned jobs as failed so a queue restart or a Wings
            // interruption cannot permanently lock this server's analyser.
            if (!$activeRun->started_at || $activeRun->started_at->lt(now()->subMinutes(10))) {
                $activeRun->update([
                    'status' => 'failed',
                    'error' => 'Spark analysis timed out before an official report was collected. You can start a new scan.',
                    'completed_at' => now(),
                ]);
                continue;
            }

            throw new DisplayException('A performance analysis is already running for this server.');
        }
        $details = $this->servers->setServer($server)->getDetails();
        if (($details['state'] ?? null) !== 'running') throw new DisplayException('The server must be online before starting performance analysis.');
        $run = $this->createRun($server, [
            'type' => "spark_{$mode}",
            'status' => 'running',
            'automatic' => $automatic,
            'trigger' => $trigger ?: null,
            'flagged_at' => $automatic && $flagged ? now() : null,
            'started_at' => now(),
            'summary' => [
                'mode' => $mode,
                'automatic' => $automatic,
                'network' => $trigger['network'] ?? null,
                'message' => 'Spark analysis started. Fluid will collect the official report link from the server log automatically.',
            ],
        ]);
        $command = match ($mode) {
            'lag_spikes' => 'spark profiler start --only-ticks-over 50 --timeout 120',
            'memory' => 'spark health --upload --memory',
            default => 'spark profiler start --timeout 60',
        };
        try {
            // Spark writes Java Flight Recorder data below plugins/spark/tmp. Paper's
            // bundled Spark does not always create this folder itself, which otherwise
            // makes a profiler command fail before it can publish a report URL.
            if ($mode !== 'memory') {
                $this->ensureSparkTemporaryDirectory($server);
            }
            $this->captureNetworkSample($server, $run);
            $this->commands->setServer($server)->send($command);
            $duration = match ($mode) {
                'memory' => 25,
                'general' => 60,
                default => 120,
            };
            // range(15, 25, 15) throws on supported PHP versions because the
            // step exceeds the remaining span. A bounded loop works for both
            // the short memory profile and longer profiler runs.
            for ($seconds = 15; $seconds <= $duration; $seconds += 15) {
                CaptureOptimizerNetworkSampleJob::dispatch($server->id, $run->id)->delay(now()->addSeconds($seconds));
            }
            CollectSparkReportJob::dispatch($server->id, $run->id)->delay(now()->addSeconds($duration + 10));
        } catch (\Throwable $exception) {
            $run->update(['status' => 'failed', 'error' => $exception->getMessage(), 'completed_at' => now()]);
            throw $exception;
        }
        return $run;
    }

    /**
     * Record a small, panel-side network sample while a Spark report is running.
     * Wings exposes cumulative counters, so the rate is calculated between each
     * sample and stored with the report for the customer-facing chart.
     */
    public function captureNetworkSample(Server $server, ServerOptimizerRun $run): void
    {
        try {
            // Server details is Wings' stable, standard endpoint and includes
            // the utilization counters needed for rate calculation.
            $metrics = $this->resourceMetrics($server, $this->servers->setServer($server)->getDetails());
            $summary = $run->summary ?? [];
            $network = $summary['network'] ?? [];
            $samples = array_values($network['samples'] ?? []);
            $previous = end($samples) ?: null;
            $sample = [
                'captured_at' => $metrics['captured_at'],
                'ingress_bytes' => $metrics['network']['ingress_bytes'] ?? 0,
                'egress_bytes' => $metrics['network']['egress_bytes'] ?? 0,
            ];

            if ($previous) {
                $capturedAt = isset($previous['captured_at']) ? \Carbon\Carbon::parse($previous['captured_at']) : now();
                $elapsed = max(1, now()->diffInSeconds($capturedAt));
                $sample['ingress_bytes_per_second'] = max(0, ($sample['ingress_bytes'] - (float) ($previous['ingress_bytes'] ?? 0)) / $elapsed);
                $sample['egress_bytes_per_second'] = max(0, ($sample['egress_bytes'] - (float) ($previous['egress_bytes'] ?? 0)) / $elapsed);
            }

            $samples[] = $sample;
            $network['samples'] = array_slice($samples, -12);
            $summary['network'] = $network;
            $run->update(['summary' => $summary]);
        } catch (\Throwable $exception) {
            // Network evidence is helpful but must not prevent Spark collection.
            // Keep the root cause in Laravel's log instead of silently producing
            // an empty chart when a node has a Wings connectivity/config issue.
            report($exception);
        }
    }

    /**
     * Ensure the directory required by Spark's async-profiler exists before asking
     * Spark to create a JFR file. This is done through Wings, so it works on every
     * node without any host-level access or a manual mkdir step.
     */
    private function ensureSparkTemporaryDirectory(Server $server): void
    {
        try {
            $files = $this->files->setServer($server);
            // Paper's bundled Spark may not have created any of these folders
            // yet. Create the complete directory chain through Wings rather than
            // assuming a third-party Spark plugin already made it.
            try {
                $files->getDirectory('/plugins');
            } catch (\Throwable) {
                $files->createDirectory('plugins', '/');
            }
            try {
                $files->getDirectory('/plugins/spark');
            } catch (\Throwable) {
                $files->createDirectory('spark', '/plugins');
            }
            foreach ($files->getDirectory('/plugins/spark') as $entry) {
                if (($entry['name'] ?? null) === 'tmp') return;
            }
            $files->createDirectory('tmp', '/plugins/spark');
        } catch (\Throwable $exception) {
            throw new DisplayException('Fluid could not prepare Spark\'s temporary profiling folder. Ensure Spark is installed and that the panel can write to plugins/spark, then try again.');
        }
    }

    public function monitor(Server $server): ?ServerOptimizerRun
    {
        if (!$server->optimizer_auto_analysis) {
            return null;
        }

        $details = $this->servers->setServer($server)->getDetails();
        if (($details['state'] ?? null) !== 'running') {
            return null;
        }

        $resource = $details;
        $metrics = $this->resourceMetrics($server, $resource);
        $cacheKey = "optimizer:resource-sample:{$server->id}";
        $previous = Cache::get($cacheKey);

        if ($previous) {
            $seconds = max(1, now()->diffInSeconds($previous['captured_at'] ?? now()));
            $metrics['network']['ingress_bytes_per_second'] = max(0, (($metrics['network']['ingress_bytes'] ?? 0) - ($previous['network']['ingress_bytes'] ?? 0)) / $seconds);
            $metrics['network']['egress_bytes_per_second'] = max(0, (($metrics['network']['egress_bytes'] ?? 0) - ($previous['network']['egress_bytes'] ?? 0)) / $seconds);
        }

        $networkRate = max($metrics['network']['ingress_bytes_per_second'] ?? 0, $metrics['network']['egress_bytes_per_second'] ?? 0);
        // This sampler runs every minute. Automatic analysis should identify
        // a real sustained degradation, not normal short-lived load while a
        // server starts, saves a world, or generates chunks.
        $signals = [
            'cpu' => ($metrics['cpu_percent'] ?? 0) >= 92,
            'memory' => ($metrics['memory_percent'] ?? 0) >= 95,
            'network' => $networkRate >= 50 * 1024 * 1024,
        ];
        $extreme = [
            'cpu' => ($metrics['cpu_percent'] ?? 0) >= 99,
            'memory' => ($metrics['memory_percent'] ?? 0) >= 99,
            'network' => $networkRate >= 150 * 1024 * 1024,
        ];
        $streaks = [];
        foreach ($signals as $signal => $concerning) {
            $streaks[$signal] = $concerning ? (($previous['streaks'][$signal] ?? 0) + 1) : 0;
        }
        $metrics['streaks'] = $streaks;
        Cache::put($cacheKey, $metrics, now()->addMinutes(10));

        $reasons = [];
        if ($extreme['cpu']) $reasons[] = 'CPU usage exceeded the emergency threshold of 99%.';
        elseif ($streaks['cpu'] >= 5) $reasons[] = 'CPU usage remained at or above 92% for five consecutive one-minute samples.';
        if ($extreme['memory']) $reasons[] = 'Memory usage exceeded the emergency threshold of 99% of the server limit.';
        elseif ($streaks['memory'] >= 5) $reasons[] = 'Memory usage remained at or above 95% for five consecutive one-minute samples.';
        if ($extreme['network']) $reasons[] = 'Network traffic exceeded the emergency threshold of 150 MiB/s.';
        elseif ($streaks['network'] >= 5) $reasons[] = 'Network traffic remained at or above 50 MiB/s for five consecutive one-minute samples.';
        if (!$reasons) {
            // A healthy server should never receive a routine automatic Spark
            // scan. Profiles are reserved for sustained degradation or an
            // emergency spike, while customers can still run one manually.
            return null;
        }

        if (!Cache::add("optimizer:auto-cooldown:{$server->id}", true, now()->addMinutes(60))) return null;

        $trigger = ['reasons' => $reasons, 'metrics' => $metrics, 'network' => $metrics['network'], 'streaks' => $streaks, 'extreme' => $extreme];
        $plugins = $this->listDirectory($server, '/plugins');
        $mods = $this->listDirectory($server, '/mods');
        $version = $this->detectVersion('', $server);

        if (($this->sparkState($server, $plugins, $mods, $version)['available'] ?? false)) {
            return $this->startProfile($server, 'lag_spikes', true, $trigger);
        }

        $run = $this->createRun($server, [
            'type' => 'automatic_resource_alert',
            'status' => 'completed',
            'automatic' => true,
            'trigger' => $trigger,
            'flagged_at' => now(),
            'started_at' => now(),
            'completed_at' => now(),
            'summary' => ['server_health' => $this->healthFromMetrics($metrics), 'network' => $metrics['network'], 'message' => 'Automatic resource alert. Spark is not available on this server, so no profiler report was collected.'],
        ]);
        foreach ($reasons as $reason) {
            $run->findings()->create($this->reportFinding('high', 'Automatic performance alert', $reason, $trigger, 'Install or enable Spark, then run a performance analysis to identify the responsible workload.'));
        }

        return $run->fresh('findings');
    }

    public function collectProfile(Server $server, ServerOptimizerRun $run): bool
    {
        $this->captureNetworkSample($server, $run);
        // captureNetworkSample persists the evolving series. Reload this model
        // before importReport merges Spark's JSON, otherwise the final update
        // can overwrite all samples with the stale summary from the job.
        $run->refresh();

        try {
            // The report URL is recent output near the end of the log. Stream
            // the file and retain a bounded tail so large logs remain usable.
            $log = $this->files->setServer($server)->getContentTail('logs/latest.log', 1048576);
        } catch (\Throwable) {
            return false;
        }

        preg_match_all('#https://spark\\.lucko\\.me/([A-Za-z0-9]{5,64})#', $log, $matches);
        $reportIds = $matches[1] ?? [];
        $reportId = $reportIds ? end($reportIds) : false;
        if (!$reportId) return false;

        $this->importReport($server, "https://spark.lucko.me/{$reportId}", $run);

        return true;
    }

    public function importReport(Server $server, string $reportUrl, ?ServerOptimizerRun $existingRun = null): ServerOptimizerRun
    {
        $reportId = $this->reportId($reportUrl);
        $run = $existingRun && $existingRun->server_id === $server->id
            ? $existingRun
            : $this->createRun($server, ['type' => 'spark_import', 'status' => 'running', 'started_at' => now()]);
        try {
            // This is Spark's documented parsed representation of its raw Protobuf report.
            // The host and report identifier are deliberately pinned to prevent SSRF.
            $response = Http::acceptJson()->timeout(30)->get("https://spark.lucko.me/{$reportId}", ['raw' => 1, 'full' => 'true']);
            if (!$response->successful()) throw new DisplayException('Spark could not provide this report. It may have expired or the link is invalid.');
            if (strlen($response->body()) > 25 * 1024 * 1024) throw new DisplayException('This Spark report is too large to import safely.');
            $report = $response->json();
            if (!is_array($report) || !in_array($report['type'] ?? null, ['sampler', 'health'], true)) throw new DisplayException('That link is not a supported Spark sampler or health report.');
            $summary = $this->summarizeReport($report, $reportId, $run->trigger ?? [], $run->summary ?? []);
            $update = ['status' => 'completed', 'summary' => $summary, 'completed_at' => now()];
            if ($run->automatic && !$run->flagged_at && $this->isConcerning($summary)) $update['flagged_at'] = now();
            $run->update($update);
            foreach ($this->reportFindings($report, $summary) as $finding) $run->findings()->create($finding);
            if ($run->automatic && $run->type === 'spark_memory' && $this->isConcerning($summary)) {
                try {
                    $this->startProfile($server, 'lag_spikes', true, [
                        'reasons' => ['A routine Spark health sample found concerning TPS or MSPT.'],
                        'network' => $summary['network'] ?? [],
                    ]);
                } catch (\Throwable $exception) {
                    report($exception);
                }
            }
        } catch (\Throwable $exception) {
            $run->update(['status' => 'failed', 'error' => $exception->getMessage(), 'completed_at' => now()]);
            throw $exception;
        }
        return $run->fresh('findings');
    }

    /**
     * Persist a new optimizer run and retain only useful history.
     *
     * Spark JSON-derived summaries, network samples, and findings can grow
     * quickly. Keep the ten newest performance reports per server; related
     * findings are removed by their database cascade. Configuration scans are
     * represented separately in the UI, so only its newest result is kept.
     */
    private function createRun(Server $server, array $attributes): ServerOptimizerRun
    {
        $run = $server->optimizerRuns()->create($attributes);

        // History retention is housekeeping. It must never prevent a customer
        // from starting a scan just because an older MariaDB/Laravel pairing
        // cannot execute a cleanup query.
        try {
            $this->pruneHistory($server);
        } catch (\Throwable $exception) {
            report($exception);
        }

        return $run;
    }

    /** Ensure values returned by Wings can always be stored in a MySQL JSON column. */
    private function jsonSafe(array $value): array
    {
        return json_decode(
            json_encode($value, JSON_INVALID_UTF8_SUBSTITUTE | JSON_THROW_ON_ERROR),
            true,
            512,
            JSON_THROW_ON_ERROR,
        );
    }

    /** Delete reports beyond the retained history for one server. */
    public function pruneHistory(Server $server): void
    {

        $oldPerformanceRunIds = $server->optimizerRuns()
            ->where('type', '!=', 'configuration_scan')
            ->latest('id')
            ->skip(10)
            // MariaDB does not allow a bare OFFSET. Laravel otherwise emits
            // `... OFFSET 10`, which fails before an optimizer run can begin.
            // The explicit upper limit is comfortably above retained history.
            ->take(1000000)
            ->pluck('id');
        if ($oldPerformanceRunIds->isNotEmpty()) {
            ServerOptimizerRun::query()->whereIn('id', $oldPerformanceRunIds)->delete();
        }

        $oldConfigurationRunIds = $server->optimizerRuns()
            ->where('type', 'configuration_scan')
            ->latest('id')
            ->skip(1)
            ->take(1000000)
            ->pluck('id');
        if ($oldConfigurationRunIds->isNotEmpty()) {
            ServerOptimizerRun::query()->whereIn('id', $oldConfigurationRunIds)->delete();
        }

    }

    private function rules(Server $server, ?string $version, array $configs, ?string $runtimeSoftware = null): array
    {
        $name = Str::lower(($runtimeSoftware ?? '') . ' ' . $server->egg->name . ' ' . $server->nest->name);
        $paper = Str::contains($name, ['paper', 'pufferfish', 'purpur', 'leaf']);
        $bukkit = $paper || Str::contains($name, ['spigot', 'bukkit', 'craftbukkit']);
        $rules = [];
        $properties = $configs['server.properties'] ?? '';
        $bukkitConfig = $configs['bukkit.yml'] ?? '';
        $spigot = $configs['spigot.yml'] ?? '';
        $paperGlobalPath = isset($configs['config/paper-global.yml']) ? 'config/paper-global.yml' : 'paper-global.yml';
        $paperGlobal = $configs[$paperGlobalPath] ?? '';
        $paperWorldPath = isset($configs['config/paper-world-defaults.yml']) ? 'config/paper-world-defaults.yml' : 'paper-world-defaults.yml';
        $paperWorld = $configs[$paperWorldPath] ?? $configs['paper-world.yml'] ?? '';

        if (($value = $this->scalar($properties, 'view-distance')) !== null && (int) $value > 12) {
            $rules[] = $this->finding('view-distance', 'medium', 'High view distance', 'server.properties', 'view-distance', $value, 8, 'A large view distance multiplies loaded and sent chunks for every player. Lower values reduce chunk work, but reduce the visible world radius.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/server-properties/', $this->profiles(10, 8, 6));
        }
        if (($value = $this->scalar($properties, 'simulation-distance')) !== null && (int) $value > 8) {
            $rules[] = $this->finding('simulation-distance', 'medium', 'High simulation distance', 'server.properties', 'simulation-distance', $value, 6, 'Simulation distance controls how far entities, redstone, and blocks tick around players. Reducing it is a gameplay trade-off.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/server-properties/', $this->profiles(8, 6, 4));
        }
        if (($value = $this->scalar($properties, 'max-chained-neighbor-updates')) !== null && (int) $value > 100000) {
            $rules[] = $this->finding('chained-neighbor-updates', 'low', 'Very high chained update limit', 'server.properties', 'max-chained-neighbor-updates', $value, 100000, 'This cap protects a tick from an excessive chain of block-neighbour updates. A smaller limit can prevent redstone or update storms, but may skip remaining updates when the cap is reached.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/server-properties/', $this->profiles(200000, 100000, 50000));
        }
        if (($value = $this->scalar($properties, 'max-tick-time')) !== null && (int) $value < 0) {
            $rules[] = $this->finding('watchdog-disabled', 'high', 'Server watchdog is disabled', 'server.properties', 'max-tick-time', $value, 60000, 'With the watchdog disabled, a fully stalled tick can leave the server unresponsive indefinitely. Restoring the documented 60-second watchdog protects availability.', 'high', false, true, 'https://docs.papermc.io/paper/reference/server-properties/');
        }
        if (($value = $this->scalar($properties, 'use-native-transport')) !== null && in_array(Str::lower($value), ['false', '0'], true)) {
            $rules[] = $this->finding('native-transport', 'low', 'Native transport is disabled', 'server.properties', 'use-native-transport', $value, true, 'Paper documents native transport as a Linux networking performance improvement. It does not change gameplay.', 'low', false, true, 'https://docs.papermc.io/paper/reference/server-properties/');
        }

        if ($bukkit && ($value = $this->scalar($bukkitConfig, 'autosave')) !== null && (int) $value > 0 && (int) $value < 6000) {
            $rules[] = $this->finding('frequent-autosave', 'low', 'Frequent world autosaves', 'bukkit.yml', 'autosave', $value, 12000, 'Very frequent full autosaves can cause regular disk pressure. Longer intervals improve throughput but increase the amount of progress that could be lost after an unexpected crash.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/bukkit-configuration/', $this->profiles(18000, 12000, 6000));
        }
        if ($bukkit && ($value = $this->scalar($bukkitConfig, 'connection-throttle')) !== null && (int) $value === 0) {
            $rules[] = $this->finding('connection-throttle', 'low', 'Connection throttle disabled', 'bukkit.yml', 'connection-throttle', $value, 4000, 'No connection throttle makes join floods more expensive to process. The Bukkit default of 4000 ms provides a basic per-IP guard.', 'low', false, true, 'https://docs.papermc.io/paper/reference/bukkit-configuration/');
        }
        if ($bukkit && ($value = $this->yamlScalar($bukkitConfig, 'spawn-limits.monsters')) !== null && (int) $value > 70) {
            $rules[] = $this->finding('monster-spawn-limit', 'medium', 'High monster spawn limit', 'bukkit.yml', 'spawn-limits.monsters', $value, 50, 'A high monster cap increases the amount of AI and collision work in loaded chunks. Lower limits trade mob density for more consistent tick time.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/bukkit-configuration/', $this->profiles(90, 50, 30));
        }
        if ($bukkit && ($value = $this->yamlScalar($bukkitConfig, 'spawn-limits.animals')) !== null && (int) $value > 15) {
            $rules[] = $this->finding('animal-spawn-limit', 'low', 'High animal spawn limit', 'bukkit.yml', 'spawn-limits.animals', $value, 10, 'Passive mobs add AI and pathfinding pressure. A lower cap is useful for survival servers with large animal farms, but reduces natural animal density.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/bukkit-configuration/', $this->profiles(25, 10, 5));
        }
        if ($bukkit && ($value = $this->yamlScalar($bukkitConfig, 'ticks-per.monster-spawns')) !== null && (int) $value > 0 && (int) $value < 2) {
            $rules[] = $this->finding('monster-spawn-ticks', 'low', 'Monster spawning runs every tick', 'bukkit.yml', 'ticks-per.monster-spawns', $value, 2, 'Increasing the interval between monster spawn attempts reduces repeated spawn searches. It also lowers the rate at which mobs naturally appear.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/bukkit-configuration/', $this->profiles(1, 2, 4));
        }

        if ($bukkit && ($value = $this->scalar($spigot, 'hopper-transfer')) !== null && (int) $value < 8) {
            $rules[] = $this->finding('hopper-transfer', 'medium', 'Frequent hopper transfers', 'spigot.yml', 'hopper-transfer', $value, 8, 'Hoppers are a common source of repeated tick work. Higher values reduce work but slow item movement.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/spigot-configuration/', $this->profiles(4, 8, 12));
        }
        if ($bukkit && ($value = $this->scalar($spigot, 'hopper-check')) !== null && (int) $value < 8) {
            $rules[] = $this->finding('hopper-check', 'medium', 'Frequent hopper checks', 'spigot.yml', 'hopper-check', $value, 8, 'Hopper checks can multiply with large farms. Higher values reduce repeated checks but can affect item timing.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/spigot-configuration/', $this->profiles(4, 8, 12));
        }
        if ($bukkit && ($value = $this->scalar($spigot, 'max-tnt-per-tick')) !== null && (int) $value < 0) {
            $rules[] = $this->finding('unlimited-tnt', 'medium', 'TNT work is not capped', 'spigot.yml', 'max-tnt-per-tick', $value, 100, 'An unlimited TNT tick budget allows a single explosion machine to monopolize a tick. A cap protects responsiveness but can slow very large TNT machines.', 'high', true, true, 'https://docs.papermc.io/paper/reference/spigot-configuration/', $this->profiles(200, 100, 50));
        }
        if ($bukkit && ($value = $this->yamlScalar($spigot, 'world-settings.default.merge-radius.item')) !== null && (float) $value < 2.5) {
            $rules[] = $this->finding('item-merge-radius', 'low', 'Small item merge radius', 'spigot.yml', 'world-settings.default.merge-radius.item', $value, 4.0, 'A larger item merge radius reduces the number of live item entities. It can change how quickly items merge and should be tested with farms.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/spigot-configuration/', $this->profiles(2.5, 4.0, 6.0));
        }
        if ($bukkit && ($value = $this->yamlScalar($spigot, 'world-settings.default.merge-radius.exp')) !== null && (float) $value < 4.0) {
            $rules[] = $this->finding('experience-merge-radius', 'low', 'Small experience merge radius', 'spigot.yml', 'world-settings.default.merge-radius.exp', $value, 6.0, 'Increasing experience-orb merging reduces entity count in mob farms, but changes the distance at which experience combines.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/spigot-configuration/', $this->profiles(4.0, 6.0, 8.0));
        }
        if ($bukkit && ($value = $this->yamlScalar($spigot, 'world-settings.default.entity-activation-range.monsters')) !== null && (int) $value > 32) {
            $rules[] = $this->finding('monster-activation-range', 'medium', 'Large monster activation range', 'spigot.yml', 'world-settings.default.entity-activation-range.monsters', $value, 32, 'A large activation range keeps more monsters ticking around each player. Reducing it lowers AI cost but can affect distant mob behaviour.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/spigot-configuration/', $this->profiles(48, 32, 24));
        }
        if ($bukkit && ($value = $this->yamlScalar($spigot, 'world-settings.default.entity-activation-range.animals')) !== null && (int) $value > 24) {
            $rules[] = $this->finding('animal-activation-range', 'low', 'Large animal activation range', 'spigot.yml', 'world-settings.default.entity-activation-range.animals', $value, 24, 'Reducing animal activation range lowers pathfinding and AI work in animal-heavy bases, with a trade-off to distant animal behaviour.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/spigot-configuration/', $this->profiles(32, 24, 16));
        }
        if ($bukkit && ($value = $this->yamlScalar($spigot, 'world-settings.default.tick-inactive-villagers')) !== null && Str::lower($value) === 'true') {
            $rules[] = $this->finding('inactive-villager-ticking', 'medium', 'Inactive villagers keep ticking', 'spigot.yml', 'world-settings.default.tick-inactive-villagers', $value, false, 'Villagers are especially expensive because of pathfinding and POI logic. Disabling inactive ticking can reduce load but may affect villager farms outside activation range.', 'high', true, true, 'https://docs.papermc.io/paper/reference/spigot-configuration/', [['label' => 'Safe: Disable', 'value' => false]]);
        }
        if ($bukkit && ($value = $this->yamlScalar($spigot, 'world-settings.default.nerf-spawner-mobs')) !== null && Str::lower($value) === 'false') {
            $rules[] = $this->finding('spawner-mob-ai', 'medium', 'Spawner mobs run full AI', 'spigot.yml', 'world-settings.default.nerf-spawner-mobs', $value, true, 'Nerfing the AI of spawner mobs greatly reduces farm load, but changes how those mobs behave and is not suitable for every gameplay style.', 'high', true, true, 'https://docs.papermc.io/paper/reference/spigot-configuration/', [['label' => 'Safe: Enable', 'value' => true]]);
        }
        if ($bukkit && ($value = $this->yamlScalar($spigot, 'world-settings.default.entity-tracking-range.monsters')) !== null && (int) $value > 64) {
            $rules[] = $this->finding('monster-tracking-range', 'low', 'Large monster tracking range', 'spigot.yml', 'world-settings.default.entity-tracking-range.monsters', $value, 48, 'Large tracking ranges increase entity updates and network traffic. Lower values reduce bandwidth and processing but make distant entities disappear sooner.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/spigot-configuration/', $this->profiles(96, 48, 32));
        }

        if ($paper && ($value = $this->scalar($paperWorld, 'max-auto-save-chunks-per-tick')) !== null && (int) $value > 24) {
            $rules[] = $this->finding('auto-save-chunks', 'low', 'Large auto-save chunk batch', $paperWorldPath, 'max-auto-save-chunks-per-tick', $value, 24, 'Saving too many chunks in one tick can create periodic disk spikes. Lower batches spread the work over more ticks.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/world-configuration/', $this->profiles(48, 24, 12));
        }
        if ($paper && ($value = $this->scalar($paperWorld, 'redstone-implementation')) !== null && Str::upper($value) === 'VANILLA') {
            $rules[] = $this->finding('redstone-implementation', 'informational', 'Vanilla redstone implementation', $paperWorldPath, 'redstone-implementation', $value, 'EIGENCRAFT', 'Paper provides alternate redstone implementations that can reduce redstone update work. Both alternatives intentionally change redstone behaviour, so choose only after testing your builds.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/world-configuration/', [
                ['label' => 'EigenCraft', 'value' => 'EIGENCRAFT'],
                ['label' => 'Alternate Current', 'value' => 'ALTERNATE_CURRENT'],
            ]);
        }
        if ($paper && ($value = $this->scalar($paperWorld, 'update-pathfinding-on-block-update')) !== null && Str::lower($value) === 'true') {
            $rules[] = $this->finding('pathfinding-updates', 'low', 'Pathfinding recalculates on every block update', $paperWorldPath, 'update-pathfinding-on-block-update', $value, false, 'Disabling block-update pathfinding can significantly reduce work on entity-heavy or redstone-heavy servers, but mobs can react less immediately to changed terrain.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/world-configuration/', [['label' => 'Reduce pathfinding updates', 'value' => false]]);
        }
        if ($paper && ($value = $this->scalar($paperWorld, 'cooldown-when-full')) !== null && Str::lower($value) === 'false') {
            $rules[] = $this->finding('hopper-full-cooldown', 'low', 'Full hoppers retry every tick', $paperWorldPath, 'cooldown-when-full', $value, true, 'Paper can apply a short cooldown to a full hopper instead of continuously checking it. This is a safe performance improvement.', 'low', false, true, 'https://docs.papermc.io/paper/reference/world-configuration/');
        }
        if ($paper && ($value = $this->scalar($paperWorld, 'ignore-occluding-blocks')) !== null && Str::lower($value) === 'false') {
            $rules[] = $this->finding('hopper-occluding-blocks', 'low', 'Hoppers check occluding blocks', $paperWorldPath, 'ignore-occluding-blocks', $value, true, 'Paper can skip hopper checks for containers hidden inside occluding blocks. This reduces hopper work and is normally safe for standard servers.', 'low', false, true, 'https://docs.papermc.io/paper/reference/world-configuration/');
        }
        if ($paper && ($value = $this->scalar($paperWorld, 'optimize-explosions')) !== null && Str::lower($value) === 'false') {
            $rules[] = $this->finding('optimize-explosions', 'medium', 'Explosion optimization disabled', $paperWorldPath, 'optimize-explosions', $value, true, 'Paper can cache entity lookups during explosions instead of recalculating them repeatedly. This significantly reduces explosion load without changing explosion outcomes.', 'medium', false, true, 'https://docs.papermc.io/paper/reference/world-configuration/');
        }
        if ($paper && ($value = $this->yamlScalar($paperWorld, 'collisions.max-entity-collisions')) !== null && (int) $value > 8) {
            $rules[] = $this->finding('entity-collision-cap', 'medium', 'High entity collision cap', $paperWorldPath, 'collisions.max-entity-collisions', $value, 8, 'Entity collision checks can dominate tick time in crowded farms. A lower cap limits collision processing but can change cramming behaviour.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/world-configuration/', $this->profiles(16, 8, 4));
        }
        if ($paper && ($value = $this->yamlScalar($paperWorld, 'entities.armor-stands.do-collision-entity-lookups')) !== null && Str::lower($value) === 'true') {
            $rules[] = $this->finding('armor-stand-collisions', 'low', 'Armor stands perform collision lookups', $paperWorldPath, 'entities.armor-stands.do-collision-entity-lookups', $value, false, 'Disabling armor-stand collision lookups reduces work in decorative builds with many stands, but may affect collision-sensitive maps.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/world-configuration/', [['label' => 'Safe: Disable', 'value' => false]]);
        }
        if ($paper && ($value = $this->yamlScalar($paperWorld, 'entities.behavior.zombies-target-turtle-eggs')) !== null && Str::lower($value) === 'true') {
            $rules[] = $this->finding('turtle-egg-targeting', 'low', 'Zombies target turtle eggs', $paperWorldPath, 'entities.behavior.zombies-target-turtle-eggs', $value, false, 'Disabling turtle-egg targeting stops nearby search work. It can affect farms that intentionally use turtle eggs.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/world-configuration/', [['label' => 'Safe: Disable', 'value' => false]]);
        }
        if ($paper && ($value = $this->yamlScalar($paperWorld, 'entities.spawning.spawn-limits.monster')) !== null && (int) $value > 70) {
            $rules[] = $this->finding('paper-monster-limit', 'medium', 'High Paper monster spawn limit', $paperWorldPath, 'entities.spawning.spawn-limits.monster', $value, 50, 'Paper world spawn limits override Bukkit values. Lowering this cap reduces AI and collision pressure in busy worlds at the cost of lower mob density.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/world-configuration/', $this->profiles(90, 50, 30));
        }
        if ($paper && ($value = $this->yamlScalar($paperGlobal, 'chunk-loading-advanced.player-max-concurrent-chunk-generates')) !== null && (int) $value < 0) {
            $rules[] = $this->finding('chunk-generate-limit', 'medium', 'Per-player chunk generation is unlimited', $paperGlobalPath, 'chunk-loading-advanced.player-max-concurrent-chunk-generates', $value, 2, 'Unlimited concurrent chunk generation lets one player create expensive generation pressure. A per-player cap smooths exploration at the cost of slower terrain generation.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/global-configuration/', $this->profiles(4, 2, 1));
        }
        if ($paper && ($value = $this->yamlScalar($paperGlobal, 'chunk-loading-basic.player-max-chunk-load-rate')) !== null && (float) $value < 0) {
            $rules[] = $this->finding('chunk-load-rate', 'medium', 'Per-player chunk load rate is unlimited', $paperGlobalPath, 'chunk-loading-basic.player-max-chunk-load-rate', $value, 100, 'Rate-limiting chunk loads protects the server from sustained exploration pressure while retaining normal gameplay.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/global-configuration/', $this->profiles(150, 100, 75));
        }

        if (!$bukkit) $rules[] = ['severity' => 'informational', 'title' => 'No implementation-specific safe fixes', 'explanation' => 'Only settings documented for the detected implementation and version are recommended. This implementation has no safe built-in rule set yet.', 'impact' => 'unknown', 'gameplay_change' => false, 'restart_required' => false, 'source' => null, 'evidence' => ['implementation' => $server->egg->name, 'version' => $version], 'recommendation' => null];
        return $rules;
    }

    private function scalar(string $content, string $key): ?string
    {
        if ($content === '' || !preg_match('/^\\s*' . preg_quote($key, '/') . '\\s*[=:]\\s*([^#\\r\\n]+)/mi', $content, $match)) return null;
        return trim($match[1], " \\t\\\"'");
    }

    private function profiles(int|float|string $risky, int|float|string $safe, int|float|string $verySafe): array
    {
        return [
            ['label' => "Risky: {$risky}", 'value' => $risky],
            ['label' => "Safe: {$safe}", 'value' => $safe],
            ['label' => "Very Safe: {$verySafe}", 'value' => $verySafe],
        ];
    }

    private function reportId(string $url): string
    {
        $parts = parse_url(trim($url));
        if (($parts['scheme'] ?? null) !== 'https' || ($parts['host'] ?? null) !== 'spark.lucko.me') throw new DisplayException('Only an official https://spark.lucko.me report link can be imported.');
        $id = trim($parts['path'] ?? '/', '/');
        if (!preg_match('/^[A-Za-z0-9]{5,64}$/', $id)) throw new DisplayException('The Spark report link is invalid.');
        return $id;
    }

    private function summarizeReport(array $report, string $reportId, array $trigger = [], array $existingSummary = []): array
    {
        $metadata = $report['metadata'] ?? [];
        $platform = $metadata['platform'] ?? [];
        $statistics = $metadata['platformStatistics'] ?? [];
        $system = $metadata['systemStatistics'] ?? [];
        $windows = array_values($report['timeWindowStatistics'] ?? []);
        $latest = $windows ? end($windows) : [];
        $network = $trigger['network'] ?? $existingSummary['network'] ?? [];
        $samples = array_values($network['samples'] ?? []);
        if ($samples) {
            $network['ingress_bytes_per_second'] = max(array_map(fn (array $sample) => (float) ($sample['ingress_bytes_per_second'] ?? 0), $samples));
            $network['egress_bytes_per_second'] = max(array_map(fn (array $sample) => (float) ($sample['egress_bytes_per_second'] ?? 0), $samples));
        }

        $summary = [
            'report_id' => $reportId,
            'report_type' => $report['type'],
            'implementation' => $platform['name'] ?? null,
            'minecraft_version' => $platform['minecraftVersion'] ?? null,
            'tps' => $latest['tps'] ?? data_get($statistics, 'tps.last1m'),
            'mspt_median' => $latest['msptMedian'] ?? data_get($statistics, 'mspt.last1m.median'),
            'mspt_p95' => data_get($statistics, 'mspt.last1m.percentile95'),
            'cpu' => $latest['cpuProcess'] ?? data_get($system, 'cpu.processUsage.last1m'),
            'memory_used' => data_get($statistics, 'memory.heap.used'),
            'memory_max' => data_get($statistics, 'memory.heap.max'),
            'gc' => $statistics['gc'] ?? [],
            'entities' => $latest['entities'] ?? data_get($statistics, 'world.totalEntities'),
            'block_entities' => $latest['tileEntities'] ?? null,
            'chunks' => $latest['chunks'] ?? null,
            'players' => data_get($statistics, 'players.online') ?? data_get($statistics, 'playerCount') ?? data_get($latest, 'players'),
            'network' => $network ?: null,
        ];
        $summary['plugin_usage'] = $this->hotspots($report);
        $summary['server_health'] = $this->healthFromReport($summary);
        $summary['analysis'] = $this->performanceAnalysis($summary);

        return $summary;
    }

    private function reportFindings(array $report, array $summary): array
    {
        $findings = [];
        if (($summary['tps'] ?? 20) < 18) $findings[] = $this->reportFinding('high', 'Low TPS observed', sprintf('Spark recorded TPS of %.2f.', $summary['tps']), ['tps' => $summary['tps']], 'Investigate the profiler hotspots below before changing server settings.');
        if (($summary['mspt_p95'] ?? $summary['mspt_median'] ?? 0) > 50) $findings[] = $this->reportFinding('high', 'Tick time exceeds the 50ms budget', sprintf('Spark reported MSPT median %s and P95 %s.', $summary['mspt_median'] ?? 'unknown', $summary['mspt_p95'] ?? 'unknown'), ['mspt_median' => $summary['mspt_median'] ?? null, 'mspt_p95' => $summary['mspt_p95'] ?? null], 'Use the evidence-backed hotspot list to investigate the responsible code or workload.');
        if (($summary['memory_max'] ?? 0) > 0 && ($summary['memory_used'] / $summary['memory_max']) > .9) $findings[] = $this->reportFinding('medium', 'High heap utilisation', sprintf('Spark recorded %.1f%% of configured heap in use.', 100 * $summary['memory_used'] / $summary['memory_max']), ['memory_used' => $summary['memory_used'], 'memory_max' => $summary['memory_max']], 'Review GC findings and memory-heavy plugins/mods; do not trigger heap dumps automatically.');
        foreach ($summary['plugin_usage'] ?? $this->hotspots($report) as $hotspot) {
            $findings[] = $this->reportFinding($hotspot['percent'] >= 25 ? 'high' : 'medium', $hotspot['title'], sprintf('%s accounted for %.1f%% of sampled server-thread time.', $hotspot['source'], $hotspot['percent']), $hotspot, 'Update, configure, or investigate this specific code path. Confidence is based on Spark source attribution.');
        }
        $network = $summary['network'] ?? [];
        $networkRate = max((float) ($network['ingress_bytes_per_second'] ?? 0), (float) ($network['egress_bytes_per_second'] ?? 0));
        if ($networkRate >= 20 * 1024 * 1024) $findings[] = $this->reportFinding('medium', 'High network traffic during performance degradation', sprintf('Fluid observed peak traffic of %.2f MiB/s while this analysis was triggered.', $networkRate / 1024 / 1024), $network, 'Review edge firewall and DDoS telemetry alongside connection logs. Spark cannot prove whether traffic is a DDoS, exploit, or normal player activity.');
        if (($summary['players'] ?? null) !== null && (($summary['tps'] ?? 20) < 18 || ($summary['mspt_p95'] ?? 0) > 50)) $findings[] = $this->reportFinding('informational', 'Player activity should be reviewed', sprintf('Spark reported %s player(s) while degraded tick performance was observed.', $summary['players']), ['players' => $summary['players']], 'Compare the player count, entities, chunks, and profiler hotspots before attributing lag to player activity.');
        return $findings;
    }

    private function resourceMetrics(Server $server, array $resource): array
    {
        // Wings' standard server-details response exposes counters below
        // `utilization`. Keep older field locations as compatible fallbacks.
        $memory = (float) (data_get($resource, 'utilization.memory_bytes') ?? data_get($resource, 'memory_bytes') ?? data_get($resource, 'memory.bytes') ?? data_get($resource, 'resources.memory_bytes') ?? 0);
        $cpu = (float) (data_get($resource, 'utilization.cpu_absolute') ?? data_get($resource, 'cpu_absolute') ?? data_get($resource, 'cpu.absolute') ?? data_get($resource, 'resources.cpu_absolute') ?? 0);
        $ingress = (float) (data_get($resource, 'utilization.network.rx_bytes') ?? data_get($resource, 'network.rx_bytes') ?? data_get($resource, 'network_rx_bytes') ?? data_get($resource, 'resources.network.rx_bytes') ?? 0);
        $egress = (float) (data_get($resource, 'utilization.network.tx_bytes') ?? data_get($resource, 'network.tx_bytes') ?? data_get($resource, 'resources.network.tx_bytes') ?? 0);
        $limit = $server->memory > 0 ? $server->memory * 1024 * 1024 : null;

        return [
            'captured_at' => now()->toIso8601String(),
            'cpu_percent' => $cpu,
            'memory_bytes' => $memory,
            'memory_percent' => $limit ? $memory / $limit * 100 : null,
            'network' => ['ingress_bytes' => $ingress, 'egress_bytes' => $egress],
        ];
    }

    private function healthFromMetrics(array $metrics): array
    {
        $score = max(0, min(100, 100 - max(0, ($metrics['cpu_percent'] ?? 0) - 65) - max(0, ($metrics['memory_percent'] ?? 0) - 75)));
        $score = round($score);

        return ['score' => $score, 'status' => $this->healthStatus($score)];
    }

    private function configurationHealth(int $actionable): array
    {
        $score = max(0, 100 - $actionable * 15);

        return ['score' => $score, 'status' => $this->healthStatus($score)];
    }

    private function healthFromReport(array $summary): array
    {
        $score = 100.0;
        if (($summary['tps'] ?? 20) < 19) $score -= min(45, (19 - (float) $summary['tps']) * 15);
        if (($summary['mspt_p95'] ?? $summary['mspt_median'] ?? 0) > 50) $score -= min(35, ((float) ($summary['mspt_p95'] ?? $summary['mspt_median']) - 50) / 2);
        if (($summary['memory_max'] ?? 0) > 0) $score -= max(0, (($summary['memory_used'] ?? 0) / $summary['memory_max'] * 100) - 85);
        $score = max(0, min(100, $score));
        $score = round($score);

        return ['score' => $score, 'status' => $this->healthStatus($score)];
    }

    private function healthStatus(float $score): string
    {
        return $score >= 90 ? 'very_healthy' : ($score >= 75 ? 'healthy' : ($score >= 55 ? 'caution' : ($score >= 30 ? 'poor' : 'critical')));
    }

    private function performanceAnalysis(array $summary): array
    {
        $health = $summary['server_health'] ?? ['score' => 100, 'status' => 'very_healthy'];
        $score = (int) ($health['score'] ?? 100);
        $conclusion = match ($health['status'] ?? 'very_healthy') {
            'healthy' => 'Healthy',
            'caution' => 'Caution',
            'poor' => 'Poor',
            'critical' => 'Critical',
            default => 'Very Healthy',
        };
        $signals = [];
        if (($summary['tps'] ?? 20) < 19) $signals[] = 'TPS was below the ideal 19–20 range.';
        if (($summary['mspt_p95'] ?? $summary['mspt_median'] ?? 0) > 50) $signals[] = 'P95 tick time exceeded the 50ms tick budget.';
        if (($summary['memory_max'] ?? 0) > 0 && (($summary['memory_used'] ?? 0) / $summary['memory_max']) > .85) $signals[] = 'Java heap usage was elevated.';
        if (max((float) data_get($summary, 'network.ingress_bytes_per_second', 0), (float) data_get($summary, 'network.egress_bytes_per_second', 0)) >= 20 * 1024 * 1024) $signals[] = 'High network traffic coincided with this report.';

        return [
            'normal' => !$signals && $score >= 90,
            'conclusion' => $conclusion,
            'message' => $signals ? implode(' ', $signals) : 'Spark completed normally. No performance concerns were identified in this sample.',
            'signals' => $signals,
        ];
    }

    private function isConcerning(array $summary): bool
    {
        return ($summary['server_health']['score'] ?? 100) < 80
            || ($summary['tps'] ?? 20) < 18
            || ($summary['mspt_p95'] ?? $summary['mspt_median'] ?? 0) > 50;
    }

    private function hotspots(array $report): array
    {
        // Spark's raw report maps sampled classes/methods to source IDs, but
        // the exact JSON representation has varied between viewer versions.
        // Attribute only a frame's self time: summing every parent frame would
        // otherwise count the same work many times and produce misleading
        // plugin percentages.
        $threads = collect($report['threads'] ?? [])->filter(fn (array $item) => Str::contains(Str::lower($item['name'] ?? ''), ['server thread', 'main thread']));
        if ($threads->isEmpty()) return [];

        $sources = data_get($report, 'metadata.sources', []);
        $classSources = is_array($report['classSources'] ?? null) ? $report['classSources'] : [];
        $methodSources = is_array($report['methodSources'] ?? null) ? $report['methodSources'] : [];
        $totals = [];
        $total = 0.0;

        $walk = function (array $node) use (&$walk, &$totals, &$total, $sources, $classSources, $methodSources): void {
            $time = $this->nodeTime($node);
            $children = is_array($node['children'] ?? null) ? $node['children'] : [];
            $childrenTime = array_sum(array_map(fn (array $child) => $this->nodeTime($child), $children));
            $selfTime = max(0, $time - $childrenTime);
            $source = $this->sparkSourceForNode($node, $sources, $classSources, $methodSources);

            if ($source && $selfTime > 0) $totals[$source] = ($totals[$source] ?? 0) + $selfTime;
            foreach ($children as $child) if (is_array($child)) $walk($child);
        };

        foreach ($threads as $thread) {
            $total += $this->nodeTime($thread);
            foreach ((array) ($thread['children'] ?? []) as $child) if (is_array($child)) $walk($child);
        }
        if ($total <= 0) return [];

        return collect($totals)
            ->map(fn (float $time, string $source) => [
                'source' => $source,
                'percent' => round(100 * $time / $total, 2),
                'title' => 'Profiler hotspot: ' . $source,
            ])
            ->filter(fn (array $item) => $item['percent'] >= .5)
            ->sortByDesc('percent')
            ->take(5)
            ->values()
            ->all();
    }

    private function nodeTime(array $node): float
    {
        return (float) ($node['time'] ?? array_sum((array) ($node['times'] ?? [])));
    }

    private function sparkSourceForNode(array $node, array $sources, array $classSources, array $methodSources): ?string
    {
        $class = trim((string) ($node['className'] ?? $node['class'] ?? ''));
        if ($class === '') return null;

        $method = trim((string) ($node['methodName'] ?? $node['method'] ?? ''));
        $classes = array_unique([$class, str_replace('.', '/', $class), str_replace('/', '.', $class)]);
        $sourceId = null;
        foreach ($classes as $candidate) {
            foreach ([$candidate . '#' . $method, $candidate . '::' . $method, $candidate] as $key) {
                if ($method !== '' && isset($methodSources[$key])) {
                    $sourceId = $methodSources[$key];
                    break 2;
                }
                if (isset($classSources[$key])) {
                    $sourceId = $classSources[$key];
                    break 2;
                }
            }
        }
        if (!is_string($sourceId) || $sourceId === '') return null;

        $metadata = $sources[$sourceId] ?? null;
        if (is_array($metadata) && Str::contains(Str::lower((string) ($metadata['type'] ?? $metadata['kind'] ?? 'plugin')), 'mod')) return null;
        $name = is_array($metadata)
            ? ($metadata['name'] ?? $metadata['displayName'] ?? $metadata['id'] ?? $sourceId)
            : (is_string($metadata) && $metadata !== '' ? $metadata : $sourceId);

        return is_string($name) && $name !== '' ? $name : null;
    }

    private function reportFinding(string $severity, string $title, string $explanation, array $evidence, string $recommendation): array
    { return ['severity' => $severity, 'title' => $title, 'explanation' => $explanation, 'impact' => $severity === 'high' ? 'high' : 'medium', 'gameplay_change' => false, 'restart_required' => false, 'evidence' => $evidence, 'recommendation' => ['manual' => $recommendation]]; }

    private function finding(string $id, string $severity, string $title, string $file, string $key, string $observed, int|float|string|bool $value, string $explanation, string $impact, bool $gameplay, bool $restart, string $source, array $options = []): array
    {
        return [
            'rule_id' => $id,
            'severity' => $severity,
            'title' => $title,
            'explanation' => $explanation,
            'impact' => $impact,
            'gameplay_change' => $gameplay,
            'restart_required' => $restart,
            'source' => $source,
            'evidence' => ['file' => $file, 'key' => $key, 'observed' => $observed],
            'recommendation' => ['file' => $file, 'key' => $key, 'value' => $value, 'options' => $options],
        ];
    }
    private function listDirectory(Server $server, string $path): array { try { return collect($this->files->setServer($server)->getDirectory($path))->pluck('name')->values()->all(); } catch (\Throwable) { return []; } }
    private function detectVersion(string $properties, Server $server): ?string
    {
        if (preg_match('/^.*(?:minecraft|version).*?([0-9]+\.[0-9]+(?:\.[0-9]+)?)/mi', $properties, $match)) return $match[1];
        foreach ($server->variables as $variable) {
            $label = implode(' ', [$variable->name ?? '', $variable->env_variable ?? '', $variable->description ?? '']);
            $value = $variable->server_value ?? $variable->default_value ?? '';
            if (preg_match('/(?:minecraft|mc)[\s_-]*version|^version$/i', $label) && preg_match('/([0-9]+\.[0-9]+(?:\.[0-9]+)?)/', $value, $match)) return $match[1];
        }
        return preg_match('/([0-9]+\.[0-9]+(?:\.[0-9]+)?)/', $server->egg->name, $match) ? $match[1] : null;
    }
    private function detectJava(string $image): ?string { return preg_match('/java[^0-9]*([0-9]+)/i', $image, $match) ? $match[1] : null; }
    private function sparkState(Server $server, array $plugins, array $mods, ?string $version, ?string $runtimeSoftware = null): array { $builtIn = Str::contains(Str::lower(($runtimeSoftware ?? '') . ' ' . $server->egg->name . ' ' . $server->nest->name), ['paper', 'leaf']) && (!$version || version_compare($version, '1.21.0', '>=')); return ['available' => $builtIn || collect([...$plugins, ...$mods])->contains(fn ($name) => Str::contains(Str::lower($name), 'spark')), 'built_in' => $builtIn, 'install_supported' => !$builtIn]; }
    private function replaceValue(string $content, string $key, string $value): string
    {
        if (str_contains($key, '.')) return $this->replaceYamlValue($content, $key, $value);

        // server.properties uses '=' while simple YAML settings use ':'. Rebuild
        // the line rather than interpolating preg_replace captures, which can
        // corrupt a replacement value that begins with a digit.
        $lines = preg_split('/(\r?\n)/', $content, -1, PREG_SPLIT_DELIM_CAPTURE);
        for ($index = 0; $index < count($lines); $index += 2) {
            if (!preg_match('/^(\s*' . preg_quote($key, '/') . '\s*[=:]\s*)[^#\r\n]*?(\s*(?:#.*)?)$/i', $lines[$index], $match)) {
                continue;
            }

            $lines[$index] = $match[1] . $value . $match[2];
            return implode('', $lines);
        }

        return $content;
    }

    private function yamlScalar(string $content, string $path): ?string
    {
        $target = explode('.', $path);
        $stack = [];

        foreach (preg_split('/\r?\n/', $content) as $line) {
            if (!preg_match('/^(\s*)([^:#][^:]*):\s*(.*?)\s*(?:#.*)?$/', $line, $match)) continue;
            $indent = strlen($match[1]);
            while ($stack && end($stack)['indent'] >= $indent) array_pop($stack);
            $key = trim($match[2], " \t\"'");
            $value = trim($match[3], " \t\"'");
            $candidate = [...array_column($stack, 'key'), $key];
            if ($candidate === $target && $value !== '') return $value;
            if ($value === '') $stack[] = ['indent' => $indent, 'key' => $key];
        }

        return null;
    }

    private function replaceYamlValue(string $content, string $path, string $value): string
    {
        $target = explode('.', $path);
        $stack = [];
        $lines = preg_split('/(\r?\n)/', $content, -1, PREG_SPLIT_DELIM_CAPTURE);

        for ($index = 0; $index < count($lines); $index += 2) {
            $line = $lines[$index];
            if (!preg_match('/^(\s*)([^:#][^:]*):(\s*)([^#\r\n]*)(.*)$/', $line, $match)) continue;
            $indent = strlen($match[1]);
            while ($stack && end($stack)['indent'] >= $indent) array_pop($stack);
            $key = trim($match[2], " \t\"'");
            $candidate = [...array_column($stack, 'key'), $key];
            if ($candidate === $target) {
                $lines[$index] = $match[1] . $match[2] . ':' . $match[3] . $value . $match[5];

                return implode('', $lines);
            }
            if (trim($match[4]) === '') $stack[] = ['indent' => $indent, 'key' => $key];
        }

        return $content;
    }
}
