<?php

namespace Pterodactyl\Http\Controllers\Api\Client\Servers;

use Carbon\Carbon;
use Illuminate\Cache\Repository;
use Illuminate\Support\Arr;
use Pterodactyl\Models\Server;
use Pterodactyl\Http\Controllers\Api\Client\ClientApiController;
use Pterodactyl\Http\Requests\Api\Client\Servers\GetServerRequest;
use Pterodactyl\Repositories\Wings\DaemonConfigurationRepository;

class NodeUptimeController extends ClientApiController
{
    public function __construct(private Repository $cache, private DaemonConfigurationRepository $repository)
    {
        parent::__construct();
    }

    /**
     * Return the most recent host uptime reported by the node-side companion.
     * Older Wings installations can still fall back to their system endpoint,
     * although it does not expose host uptime in current Wings releases.
     */
    public function __invoke(GetServerRequest $request, Server $server): array
    {
        // Wings' public system endpoint does not expose host uptime. Prefer the
        // authenticated node-side reporter when it has checked in recently.
        if ($server->node->uptime_reported_at && $server->node->uptime_reported_at->greaterThan(now()->subMinutes(3))) {
            return ['uptime' => $server->node->uptime_seconds];
        }

        $uptime = $this->cache->remember("node-uptime:{$server->node_id}", Carbon::now()->addSeconds(30), function () use ($server) {
            try {
                $system = $this->repository->setNode($server->node)->getSystemInformation(2);
                $value = Arr::first([
                    Arr::get($system, 'system.uptime_seconds'),
                    Arr::get($system, 'system.uptime'),
                    Arr::get($system, 'uptime_seconds'),
                    Arr::get($system, 'uptime'),
                ], static fn ($uptime) => is_numeric($uptime));

                return is_null($value) ? null : (int) $value;
            } catch (\Throwable) {
                return null;
            }
        });

        return ['uptime' => $uptime];
    }
}
