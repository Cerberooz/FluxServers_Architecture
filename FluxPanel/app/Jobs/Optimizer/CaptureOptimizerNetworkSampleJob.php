<?php

namespace Pterodactyl\Jobs\Optimizer;

use Illuminate\Bus\Queueable;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Bus\Dispatchable;
use Illuminate\Queue\InteractsWithQueue;
use Illuminate\Queue\SerializesModels;
use Pterodactyl\Models\Server;
use Pterodactyl\Models\ServerOptimizerRun;
use Pterodactyl\Services\Optimizer\MinecraftOptimizerService;

class CaptureOptimizerNetworkSampleJob implements ShouldQueue
{
    use Dispatchable;
    use InteractsWithQueue;
    use Queueable;
    use SerializesModels;

    public int $tries = 1;

    public function __construct(private int $serverId, private int $runId)
    {
        $this->queue = 'standard';
    }

    public function handle(MinecraftOptimizerService $service): void
    {
        $server = Server::find($this->serverId);
        $run = ServerOptimizerRun::find($this->runId);

        if (!$server || !$run || $run->server_id !== $server->id || !in_array($run->status, ['queued', 'running'], true)) {
            return;
        }

        $service->captureNetworkSample($server, $run);
    }
}
