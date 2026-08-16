<?php

namespace Pterodactyl\Console\Commands\Optimizer;

use Illuminate\Console\Command;
use Pterodactyl\Models\Server;
use Pterodactyl\Services\Optimizer\MinecraftOptimizerService;

class MonitorOptimizerCommand extends Command
{
    protected $signature = 'p:optimizer:monitor';
    protected $description = 'Collect resource signals and queue Spark analyses for concerning servers.';

    public function handle(MinecraftOptimizerService $optimizer): int
    {
        $queued = 0;

        Server::query()
            ->whereNull('status')
            ->where('optimizer_auto_analysis', true)
            ->with(['egg', 'nest', 'variables'])
            ->orderBy('id')
            ->chunkById(50, function ($servers) use ($optimizer, &$queued) {
                foreach ($servers as $server) {
                    try {
                        if ($optimizer->monitor($server)) {
                            ++$queued;
                        }
                    } catch (\Throwable $exception) {
                        report($exception);
                    }
                }
            });

        $this->info("Queued {$queued} optimizer performance analysis(es).");

        return self::SUCCESS;
    }
}
