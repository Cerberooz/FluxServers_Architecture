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
use Pterodactyl\Models\ServerOptimizerRun;
use Pterodactyl\Models\ServerOptimizerSnapshot;
use Pterodactyl\Services\Optimizer\MinecraftOptimizerService;

class OptimizerController extends ClientApiController
{
    private function mayRead(Request $request, Server $server): void { abort_unless($request->user()->can(Permission::ACTION_FILE_READ_CONTENT, $server), 403); }
    public function index(Request $request, Server $server, MinecraftOptimizerService $service): array
    {
        $this->mayRead($request, $server);
        // Also clean up pre-existing history created before retention was
        // introduced; this is idempotent and only touches this server.
        $service->pruneHistory($server);
        $page = max(1, (int) $request->query('page', 1));
        $runs = $server->optimizerRuns()
            ->where('type', '!=', 'configuration_scan')
            ->with('findings')
            ->latest()
            ->paginate(5, ['*'], 'page', $page);
        $configuration = $server->optimizerRuns()
            ->where('type', 'configuration_scan')
            ->with('findings')
            ->latest()
            ->first();

        return [
            'data' => $runs->items(),
            'configuration' => $configuration,
            'settings' => ['automatic_analysis' => $server->optimizer_auto_analysis ?? true],
            'meta' => [
                'pagination' => [
                    'current_page' => $runs->currentPage(),
                    'total_pages' => $runs->lastPage(),
                    'total' => $runs->total(),
                    'per_page' => $runs->perPage(),
                ],
                'unread' => $server->optimizerRuns()->where('automatic', true)->whereNotNull('flagged_at')->whereNull('read_at')->count(),
            ],
        ];
    }
    public function notifications(Request $request, Server $server): array
    {
        $this->mayRead($request, $server);
        return ['data' => ['unread' => $server->optimizerRuns()->where('automatic', true)->whereNotNull('flagged_at')->whereNull('read_at')->count()]];
    }
    public function read(Request $request, Server $server, ServerOptimizerRun $run): JsonResponse
    {
        $this->mayRead($request, $server);
        abort_unless($run->server_id === $server->id, 404);
        if ($run->automatic && $run->flagged_at && !$run->read_at) $run->update(['read_at' => now()]);
        return new JsonResponse([
            'attributes' => $run->fresh('findings'),
            'meta' => ['unread' => $server->optimizerRuns()->where('automatic', true)->whereNotNull('flagged_at')->whereNull('read_at')->count()],
        ]);
    }
    public function scan(Request $request, Server $server, MinecraftOptimizerService $service): JsonResponse { $this->mayRead($request, $server); $run = $service->scan($server); Activity::event('server:optimizer.scan')->subject($server)->log(); return new JsonResponse(['attributes' => $run], 201); }
    public function profile(Request $request, Server $server, MinecraftOptimizerService $service): JsonResponse { $this->mayRead($request, $server); abort_unless($request->user()->can(Permission::ACTION_CONTROL_CONSOLE, $server), 403); $mode = $request->validate(['mode' => 'required|in:general,lag_spikes,memory'])['mode']; $run = $service->startProfile($server, $mode); Activity::event('server:optimizer.profile')->subject($server)->property('mode', $mode)->log(); return new JsonResponse(['attributes' => $run], 202); }
    public function updateSettings(Request $request, Server $server): JsonResponse
    {
        $this->mayRead($request, $server);
        abort_unless($request->user()->can(Permission::ACTION_CONTROL_CONSOLE, $server), 403);

        $data = $request->validate(['automatic_analysis' => 'required|boolean']);
        // forceFill keeps this feature explicit even on installations whose
        // Server model has custom guarded fields. Refresh so the response
        // always reflects the persisted boolean rather than a stale/null value.
        $server->forceFill(['optimizer_auto_analysis' => (bool) $data['automatic_analysis']])->save();
        $server->refresh();

        Activity::event('server:optimizer.auto_analysis')->subject($server)->property('enabled', $server->optimizer_auto_analysis)->log();

        return new JsonResponse(['attributes' => ['automatic_analysis' => (bool) ($server->optimizer_auto_analysis ?? true)]]);
    }
    public function import(Request $request, Server $server, MinecraftOptimizerService $service): JsonResponse { $this->mayRead($request, $server); $data = $request->validate(['url' => 'required|string|max:255']); $run = $service->importReport($server, $data['url']); Activity::event('server:optimizer.import')->subject($server)->property('report_id', $run->summary['report_id'] ?? null)->log(); return new JsonResponse(['attributes' => $run], 201); }
    public function apply(Request $request, Server $server, ServerOptimizerFinding $finding, MinecraftOptimizerService $service): JsonResponse
    {
        $this->mayRead($request, $server);
        abort_unless(
            $request->user()->can(Permission::ACTION_FILE_UPDATE, $server)
            && $finding->run()->where('server_id', $server->id)->exists(),
            403
        );

        $data = $request->validate(['value' => ['nullable']]);
        $hasSelectedValue = array_key_exists('value', $data);
        $snapshot = $service->apply($finding, $data['value'] ?? null, $hasSelectedValue);

        Activity::event('server:optimizer.apply')->subject($server, $finding)->property('snapshot_id', $snapshot->id)->log();

        return new JsonResponse(['attributes' => $snapshot], 201);
    }
    public function rollback(Request $request, Server $server, ServerOptimizerSnapshot $snapshot, MinecraftOptimizerService $service): JsonResponse { $this->mayRead($request, $server); abort_unless($request->user()->can(Permission::ACTION_FILE_UPDATE, $server) && $snapshot->server_id === $server->id, 403); $service->rollback($snapshot); Activity::event('server:optimizer.rollback')->subject($server, $snapshot)->log(); return new JsonResponse([], 204); }
    public function ignore(Request $request, Server $server, ServerOptimizerFinding $finding): JsonResponse { $this->mayRead($request, $server); abort_unless($finding->run->server_id === $server->id, 403); $finding->update(['ignored' => true]); return new JsonResponse([], 204); }
}
