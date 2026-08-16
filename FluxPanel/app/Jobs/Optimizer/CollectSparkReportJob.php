<?php

namespace Pterodactyl\Jobs\Optimizer;

use Illuminate\Bus\Queueable;
use Illuminate\Contracts\Queue\ShouldBeUnique;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Bus\Dispatchable;
use Illuminate\Queue\InteractsWithQueue;
use Illuminate\Queue\SerializesModels;
use Pterodactyl\Models\Server;
use Pterodactyl\Models\ServerOptimizerRun;
use Pterodactyl\Services\Optimizer\MinecraftOptimizerService;

class CollectSparkReportJob implements ShouldQueue, ShouldBeUnique
{
    use Dispatchable;
    use InteractsWithQueue;
    use Queueable;
    use SerializesModels;

    public int $tries = 3;
    public array $backoff = [60, 120];
    public int $uniqueFor = 900;

    public function __construct(private int $serverId, private int $runId)
    {
        $this->queue = 'standard';
    }

    public function uniqueId(): string
    {
        return "optimizer-spark-report:{$this->runId}";
    }

    public function handle(MinecraftOptimizerService $service): void
    {
        $server = Server::find($this->serverId);
        $run = ServerOptimizerRun::find($this->runId);

        if (!$server || !$run || $run->server_id !== $server->id || !in_array($run->status, ['queued', 'running'], true)) {
            return;
        }

        if ($service->collectProfile($server, $run)) {
            return;
        }

        if ($this->attempts() < $this->tries) {
            $this->release($this->backoff[$this->attempts() - 1] ?? 120);
            return;
        }

        $run->update([
            'status' => 'failed',
            'error' => 'Spark did not write an official report URL to logs/latest.log. Check that Spark is installed and that the server can reach spark.lucko.me, then run another analysis.',
            'completed_at' => now(),
        ]);
    }
}
