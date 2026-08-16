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
     * Read the host uptime directly from Wings. The value is intentionally cached
     * since multiple servers can share a single node and every dashboard view would
     * otherwise make an identical daemon request.
     */
    public function __invoke(GetServerRequest $request, Server $server): array
    {
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
