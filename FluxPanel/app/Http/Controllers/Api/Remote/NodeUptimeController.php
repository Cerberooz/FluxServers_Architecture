<?php

namespace Pterodactyl\Http\Controllers\Api\Remote;

use Illuminate\Cache\Repository;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Pterodactyl\Http\Controllers\Controller;
use Pterodactyl\Models\Node;

class NodeUptimeController extends Controller
{
    /**
     * Receive host uptime from the small companion service installed beside
     * Wings. DaemonAuthenticate resolves the caller's node from its existing
     * token, so a node can update only its own telemetry.
     */
    public function __invoke(Request $request, Repository $cache): JsonResponse
    {
        $data = $request->validate([
            'uptime_seconds' => 'required|integer|min:0|max:315576000',
        ]);
        $node = $request->attributes->get('node');
        abort_unless($node instanceof Node, 401);

        $node->forceFill([
            'uptime_seconds' => $data['uptime_seconds'],
            'uptime_reported_at' => now(),
        ])->save();
        $cache->forget("node-uptime:{$node->id}");

        return new JsonResponse(['uptime' => $node->uptime_seconds]);
    }
}
