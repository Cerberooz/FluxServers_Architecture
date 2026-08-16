<?php

namespace Pterodactyl\Http\Controllers\Api\Client;

use Carbon\Carbon;
use Illuminate\Cache\Repository;
use Illuminate\Http\Request;
use Pterodactyl\Models\Server;
use Pterodactyl\Repositories\Wings\DaemonServerRepository;
use Pterodactyl\Services\Minecraft\MinecraftStatusService;

class DashboardStatsController extends ClientApiController
{
    public function __construct(private Repository $cache, private DaemonServerRepository $daemon, private MinecraftStatusService $minecraft)
    {
        parent::__construct();
    }

    /** Dashboard totals are fetched server-side; the browser never talks to Wings or game allocations. */
    public function __invoke(Request $request): array
    {
        $user = $request->user();
        $showAll = $request->query('type') === 'admin-all' && $user->root_admin;
        $key = sprintf('dashboard:stats:%d:%s', $user->id, $showAll ? 'admin-all' : 'accessible');

        return $this->cache->remember($key, Carbon::now()->addSeconds(15), function () use ($user, $showAll) {
            $query = Server::query()->with(['allocation', 'node']);
            if (!$showAll) $query->whereIn('servers.id', $user->accessibleServers()->select('servers.id'));

            $total = $online = $players = $playersQueried = $uptimeTotal = 0;
            foreach ($query->get() as $server) {
                ++$total;
                try {
                    $details = $this->daemon->setServer($server)->getDetails();
                    if (($details['state'] ?? null) !== 'running') continue;
                    ++$online;
                    $uptimeTotal += max(0, (int) data_get($details, 'utilization.uptime', 0));
                    // Only query an allocation IP configured by the panel, never a customer supplied host.
                    if ($server->allocation?->ip && $server->allocation?->port && ($status = $this->minecraft->players($server->allocation->ip, $server->allocation->port))) {
                        $players += $status['online'];
                        ++$playersQueried;
                    }
                } catch (\Throwable) {
                    // One unavailable node must not prevent the dashboard from loading.
                }
            }

            return [
                'total' => $total,
                'online' => $online,
                'offline' => max(0, $total - $online),
                'players_online' => $playersQueried ? $players : null,
                'players_queried' => $playersQueried,
                // Offline servers contribute zero: this is the selected set's true average uptime.
                'average_uptime' => $total ? (int) round($uptimeTotal / $total) : null,
            ];
        });
    }
}
