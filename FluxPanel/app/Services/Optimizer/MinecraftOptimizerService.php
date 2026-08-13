<?php

namespace Pterodactyl\Services\Optimizer;

use Illuminate\Support\Str;
use Illuminate\Support\Facades\Http;
use Pterodactyl\Exceptions\DisplayException;
use Pterodactyl\Models\Server;
use Pterodactyl\Models\ServerOptimizerFinding;
use Pterodactyl\Models\ServerOptimizerRun;
use Pterodactyl\Models\ServerOptimizerSnapshot;
use Pterodactyl\Repositories\Wings\DaemonCommandRepository;
use Pterodactyl\Repositories\Wings\DaemonFileRepository;
use Pterodactyl\Repositories\Wings\DaemonServerRepository;

class MinecraftOptimizerService
{
    private const FILES = ['server.properties', 'bukkit.yml', 'spigot.yml', 'paper-global.yml', 'paper-world-defaults.yml', 'paper-world.yml', 'purpur.yml', 'pufferfish.yml'];

    public function __construct(private DaemonFileRepository $files, private DaemonCommandRepository $commands, private DaemonServerRepository $servers) {}

    public function scan(Server $server): ServerOptimizerRun
    {
        $run = $server->optimizerRuns()->create(['type' => 'configuration_scan', 'status' => 'running', 'started_at' => now()]);
        try {
            $implementation = $server->egg->name . ' (' . $server->nest->name . ')';
            $configs = [];
            foreach (self::FILES as $path) {
                try { $configs[$path] = $this->files->setServer($server)->getContent($path, 524288); } catch (\Throwable) { }
            }
            $plugins = $this->listDirectory($server, '/plugins');
            $mods = $this->listDirectory($server, '/mods');
            $version = $this->detectVersion($configs['server.properties'] ?? '', $server);
            $summary = ['implementation' => $implementation, 'minecraft_version' => $version, 'java' => $this->detectJava($server->image), 'memory_mb' => $server->memory, 'cpu_percent' => $server->cpu, 'plugins' => $plugins, 'mods' => $mods, 'files_scanned' => array_keys($configs), 'spark' => $this->sparkState($server, $plugins, $mods, $version)];
            $run->update(['status' => 'completed', 'summary' => $summary, 'completed_at' => now()]);
            foreach ($this->rules($server, $version, $configs) as $finding) $run->findings()->create($finding);
        } catch (\Throwable $exception) {
            $run->update(['status' => 'failed', 'error' => $exception->getMessage(), 'completed_at' => now()]);
            throw $exception;
        }
        return $run->fresh('findings');
    }

    public function apply(ServerOptimizerFinding $finding): ServerOptimizerSnapshot
    {
        $recommendation = $finding->recommendation;
        if (!$recommendation || !isset($recommendation['file'], $recommendation['key'], $recommendation['value']) || ($finding->gameplay_change ?? false)) throw new DisplayException('This recommendation requires manual review and cannot be applied automatically.');
        $server = $finding->run->server;
        $path = $recommendation['file'];
        $content = $this->files->setServer($server)->getContent($path, 524288);
        $replacement = $this->replaceValue($content, $recommendation['key'], (string) $recommendation['value']);
        if ($replacement === $content) throw new DisplayException('The expected configuration value was not found. Scan again before applying this recommendation.');
        $snapshot = ServerOptimizerSnapshot::query()->create(['server_id' => $server->id, 'finding_id' => $finding->id, 'path' => $path, 'contents' => $content]);
        $this->files->setServer($server)->putContent($path, $replacement);
        return $snapshot;
    }

    public function rollback(ServerOptimizerSnapshot $snapshot): void
    {
        if ($snapshot->restored_at) throw new DisplayException('This snapshot has already been restored.');
        $this->files->setServer($snapshot->server)->putContent($snapshot->path, $snapshot->contents);
        $snapshot->update(['restored_at' => now()]);
    }

    public function startProfile(Server $server, string $mode): ServerOptimizerRun
    {
        $active = $server->optimizerRuns()->where('type', 'like', 'spark_%')->whereIn('status', ['queued', 'running'])->exists();
        if ($active) throw new DisplayException('A performance analysis is already running for this server.');
        $details = $this->servers->setServer($server)->getDetails();
        if (($details['state'] ?? null) !== 'running') throw new DisplayException('The server must be online before starting performance analysis.');
        $run = $server->optimizerRuns()->create(['type' => "spark_{$mode}", 'status' => 'running', 'started_at' => now(), 'summary' => ['mode' => $mode, 'message' => 'Spark command sent; the report link will appear in the server console.']]);
        $command = match ($mode) {
            'lag_spikes' => 'spark profiler start --only-ticks-over 50 --timeout 120',
            'memory' => 'spark healthreport',
            default => 'spark profiler start --timeout 120',
        };
        $this->commands->setServer($server)->send($command);
        return $run;
    }

    public function importReport(Server $server, string $reportUrl): ServerOptimizerRun
    {
        $reportId = $this->reportId($reportUrl);
        $server->optimizerRuns()->where('type', 'like', 'spark_%')->where('status', 'running')->update(['status' => 'completed', 'completed_at' => now()]);
        $run = $server->optimizerRuns()->create(['type' => 'spark_import', 'status' => 'running', 'started_at' => now()]);
        try {
            // This is Spark's documented parsed representation of its raw Protobuf report.
            // The host and report identifier are deliberately pinned to prevent SSRF.
            $response = Http::acceptJson()->timeout(30)->get("https://spark.lucko.me/{$reportId}", ['raw' => 1, 'full' => 'true']);
            if (!$response->successful()) throw new DisplayException('Spark could not provide this report. It may have expired or the link is invalid.');
            if (strlen($response->body()) > 25 * 1024 * 1024) throw new DisplayException('This Spark report is too large to import safely.');
            $report = $response->json();
            if (!is_array($report) || !in_array($report['type'] ?? null, ['sampler', 'health'], true)) throw new DisplayException('That link is not a supported Spark sampler or health report.');
            $summary = $this->summarizeReport($report, $reportId);
            $run->update(['status' => 'completed', 'summary' => $summary, 'completed_at' => now()]);
            foreach ($this->reportFindings($report, $summary) as $finding) $run->findings()->create($finding);
        } catch (\Throwable $exception) {
            $run->update(['status' => 'failed', 'error' => $exception->getMessage(), 'completed_at' => now()]);
            throw $exception;
        }
        return $run->fresh('findings');
    }

    private function rules(Server $server, ?string $version, array $configs): array
    {
        $paper = $version && Str::contains(Str::lower($server->egg->name . ' ' . $server->nest->name), ['paper', 'pufferfish', 'purpur']);
        $rules = [];
        if ($paper && isset($configs['server.properties']) && preg_match('/^view-distance=(\d+)/m', $configs['server.properties'], $match) && (int) $match[1] > 12) {
            $rules[] = $this->finding('view-distance', 'medium', 'High view distance', 'server.properties', 'view-distance', $match[1], 12, 'A high view distance increases chunks loaded and ticked for every player.', 'medium', false, true, 'https://docs.papermc.io/paper/reference/server-properties/');
        }
        if ($paper && isset($configs['server.properties']) && preg_match('/^simulation-distance=(\d+)/m', $configs['server.properties'], $match) && (int) $match[1] > 8) {
            $rules[] = $this->finding('simulation-distance', 'medium', 'High simulation distance', 'server.properties', 'simulation-distance', $match[1], 8, 'Simulation distance controls how far entities and blocks tick around players.', 'medium', true, true, 'https://docs.papermc.io/paper/reference/server-properties/');
        }
        if (!$paper) $rules[] = ['severity' => 'informational', 'title' => 'No implementation-specific safe fixes', 'explanation' => 'Only settings documented for the detected implementation and version are recommended. This implementation has no safe built-in rule set yet.', 'impact' => 'unknown', 'gameplay_change' => false, 'restart_required' => false, 'source' => null, 'evidence' => ['implementation' => $server->egg->name, 'version' => $version], 'recommendation' => null];
        return $rules;
    }

    private function reportId(string $url): string
    {
        $parts = parse_url(trim($url));
        if (($parts['scheme'] ?? null) !== 'https' || ($parts['host'] ?? null) !== 'spark.lucko.me') throw new DisplayException('Only an official https://spark.lucko.me report link can be imported.');
        $id = trim($parts['path'] ?? '/', '/');
        if (!preg_match('/^[A-Za-z0-9]{5,64}$/', $id)) throw new DisplayException('The Spark report link is invalid.');
        return $id;
    }

    private function summarizeReport(array $report, string $reportId): array
    {
        $metadata = $report['metadata'] ?? [];
        $platform = $metadata['platform'] ?? [];
        $statistics = $metadata['platformStatistics'] ?? [];
        $system = $metadata['systemStatistics'] ?? [];
        $windows = array_values($report['timeWindowStatistics'] ?? []);
        $latest = $windows ? end($windows) : [];
        return [
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
        ];
    }

    private function reportFindings(array $report, array $summary): array
    {
        $findings = [];
        if (($summary['tps'] ?? 20) < 18) $findings[] = $this->reportFinding('high', 'Low TPS observed', sprintf('Spark recorded TPS of %.2f.', $summary['tps']), ['tps' => $summary['tps']], 'Investigate the profiler hotspots below before changing server settings.');
        if (($summary['mspt_p95'] ?? $summary['mspt_median'] ?? 0) > 50) $findings[] = $this->reportFinding('high', 'Tick time exceeds the 50ms budget', sprintf('Spark reported MSPT median %s and P95 %s.', $summary['mspt_median'] ?? 'unknown', $summary['mspt_p95'] ?? 'unknown'), ['mspt_median' => $summary['mspt_median'] ?? null, 'mspt_p95' => $summary['mspt_p95'] ?? null], 'Use the evidence-backed hotspot list to investigate the responsible code or workload.');
        if (($summary['memory_max'] ?? 0) > 0 && ($summary['memory_used'] / $summary['memory_max']) > .9) $findings[] = $this->reportFinding('medium', 'High heap utilisation', sprintf('Spark recorded %.1f%% of configured heap in use.', 100 * $summary['memory_used'] / $summary['memory_max']), ['memory_used' => $summary['memory_used'], 'memory_max' => $summary['memory_max']], 'Review GC findings and memory-heavy plugins/mods; do not trigger heap dumps automatically.');
        foreach ($this->hotspots($report) as $hotspot) {
            $findings[] = $this->reportFinding($hotspot['percent'] >= 25 ? 'high' : 'medium', $hotspot['title'], sprintf('%s accounted for %.1f%% of sampled server-thread time.', $hotspot['source'], $hotspot['percent']), $hotspot, 'Update, configure, or investigate this specific code path. Confidence is based on Spark source attribution.');
        }
        return $findings;
    }

    private function hotspots(array $report): array
    {
        $thread = collect($report['threads'] ?? [])->first(fn (array $item) => Str::contains(Str::lower($item['name'] ?? ''), 'server thread'));
        if (!$thread) return [];
        $total = (float) ($thread['time'] ?? array_sum($thread['times'] ?? []));
        if ($total <= 0) return [];
        $sources = data_get($report, 'metadata.sources', []);
        $classSources = $report['classSources'] ?? [];
        $items = [];
        $walk = function (array $node, array $path) use (&$walk, &$items, $sources, $classSources, $total): void {
            $time = (float) ($node['time'] ?? array_sum($node['times'] ?? []));
            $class = $node['className'] ?? '';
            $sourceId = $classSources[$class] ?? null;
            if ($sourceId && isset($sources[$sourceId]['name']) && $time / $total >= .05) $items[] = ['source' => $sources[$sourceId]['name'], 'percent' => 100 * $time / $total, 'title' => 'Profiler hotspot: ' . $sources[$sourceId]['name'], 'hot_path' => implode(' → ', [...$path, trim($class . '::' . ($node['methodName'] ?? ''))])];
            foreach ($node['children'] ?? [] as $child) $walk($child, [...$path, trim($class . '::' . ($node['methodName'] ?? ''))]);
        };
        foreach ($thread['children'] ?? [] as $child) $walk($child, []);
        return collect($items)->sortByDesc('percent')->unique('source')->take(5)->values()->all();
    }

    private function reportFinding(string $severity, string $title, string $explanation, array $evidence, string $recommendation): array
    { return ['severity' => $severity, 'title' => $title, 'explanation' => $explanation, 'impact' => $severity === 'high' ? 'high' : 'medium', 'gameplay_change' => false, 'restart_required' => false, 'evidence' => $evidence, 'recommendation' => ['manual' => $recommendation]]; }

    private function finding(string $id, string $severity, string $title, string $file, string $key, string $observed, int $value, string $explanation, string $impact, bool $gameplay, bool $restart, string $source): array
    { return ['rule_id' => $id, 'severity' => $severity, 'title' => $title, 'explanation' => $explanation, 'impact' => $impact, 'gameplay_change' => $gameplay, 'restart_required' => $restart, 'source' => $source, 'evidence' => ['file' => $file, 'key' => $key, 'observed' => $observed], 'recommendation' => ['file' => $file, 'key' => $key, 'value' => $value]]; }
    private function listDirectory(Server $server, string $path): array { try { return collect($this->files->setServer($server)->getDirectory($path))->pluck('name')->values()->all(); } catch (\Throwable) { return []; } }
    private function detectVersion(string $properties, Server $server): ?string
    {
        if (preg_match('/^.*(?:minecraft|version).*?([0-9]+\.[0-9]+(?:\.[0-9]+)?)/mi', $properties, $match)) return $match[1];
        foreach ($server->variables as $variable) {
            if (preg_match('/minecraft.*version/i', $variable->variable->name ?? '') && preg_match('/([0-9]+\.[0-9]+(?:\.[0-9]+)?)/', $variable->variable_value, $match)) return $match[1];
        }
        return preg_match('/([0-9]+\.[0-9]+(?:\.[0-9]+)?)/', $server->egg->name, $match) ? $match[1] : null;
    }
    private function detectJava(string $image): ?string { return preg_match('/java[^0-9]*([0-9]+)/i', $image, $match) ? $match[1] : null; }
    private function sparkState(Server $server, array $plugins, array $mods, ?string $version): array { $builtIn = Str::contains(Str::lower($server->egg->name . ' ' . $server->nest->name), 'paper') && $version && version_compare($version, '1.21.0', '>='); return ['available' => $builtIn || collect([...$plugins, ...$mods])->contains(fn ($name) => Str::contains(Str::lower($name), 'spark')), 'built_in' => $builtIn, 'install_supported' => !$builtIn]; }
    private function replaceValue(string $content, string $key, string $value): string { return preg_replace('/^(' . preg_quote($key, '/') . '\s*[=:]\s*).+$/mi', '${1}' . $value, $content, 1) ?? $content; }
}
