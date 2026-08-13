<?php
namespace Pterodactyl\Http\Controllers\Api\Client\Servers;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Pterodactyl\Exceptions\DisplayException;
use Pterodactyl\Facades\Activity;
use Pterodactyl\Http\Controllers\Api\Client\ClientApiController;
use Pterodactyl\Models\Permission;
use Pterodactyl\Models\Server;
use Pterodactyl\Models\ServerOptimizerFinding;
use Pterodactyl\Models\ServerOptimizerSnapshot;
use Pterodactyl\Services\Optimizer\MinecraftOptimizerService;

class OptimizerController extends ClientApiController
{
    private function mayRead(Request $request, Server $server): void { abort_unless($request->user()->can(Permission::ACTION_FILE_READ_CONTENT, $server), 403); }
    public function index(Request $request, Server $server): array { $this->mayRead($request, $server); return ['data' => $server->optimizerRuns()->with('findings')->latest()->limit(10)->get()]; }
    public function scan(Request $request, Server $server, MinecraftOptimizerService $service): JsonResponse { $this->mayRead($request, $server); $run = $service->scan($server); Activity::event('server:optimizer.scan')->subject($server)->log(); return new JsonResponse(['attributes' => $run], 201); }
    public function profile(Request $request, Server $server, MinecraftOptimizerService $service): JsonResponse { $this->mayRead($request, $server); abort_unless($request->user()->can(Permission::ACTION_CONTROL_CONSOLE, $server), 403); $mode = $request->validate(['mode' => 'required|in:general,lag_spikes,memory'])['mode']; $run = $service->startProfile($server, $mode); Activity::event('server:optimizer.profile')->subject($server)->property('mode', $mode)->log(); return new JsonResponse(['attributes' => $run], 202); }
    public function import(Request $request, Server $server, MinecraftOptimizerService $service): JsonResponse { $this->mayRead($request, $server); $data = $request->validate(['url' => 'required|string|max:255']); $run = $service->importReport($server, $data['url']); Activity::event('server:optimizer.import')->subject($server)->property('report_id', $run->summary['report_id'] ?? null)->log(); return new JsonResponse(['attributes' => $run], 201); }
    public function apply(Request $request, Server $server, ServerOptimizerFinding $finding, MinecraftOptimizerService $service): JsonResponse { $this->mayRead($request, $server); abort_unless($request->user()->can(Permission::ACTION_FILE_UPDATE, $server) && $finding->run->server_id === $server->id, 403); $snapshot = $service->apply($finding); Activity::event('server:optimizer.apply')->subject($server, $finding)->property('snapshot_id', $snapshot->id)->log(); return new JsonResponse(['attributes' => $snapshot], 201); }
    public function rollback(Request $request, Server $server, ServerOptimizerSnapshot $snapshot, MinecraftOptimizerService $service): JsonResponse { $this->mayRead($request, $server); abort_unless($request->user()->can(Permission::ACTION_FILE_UPDATE, $server) && $snapshot->server_id === $server->id, 403); $service->rollback($snapshot); Activity::event('server:optimizer.rollback')->subject($server, $snapshot)->log(); return new JsonResponse([], 204); }
    public function ignore(Request $request, Server $server, ServerOptimizerFinding $finding): JsonResponse { $this->mayRead($request, $server); abort_unless($finding->run->server_id === $server->id, 403); $finding->update(['ignored' => true]); return new JsonResponse([], 204); }
}
