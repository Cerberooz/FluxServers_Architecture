<?php
namespace Pterodactyl\Http\Controllers\Api\Client\Servers;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
use Pterodactyl\Facades\Activity;
use Pterodactyl\Http\Controllers\Api\Client\ClientApiController;
use Pterodactyl\Models\Permission;
use Pterodactyl\Models\Server;
use Pterodactyl\Services\Plugins\ModrinthPluginService;

class PluginManagerController extends ClientApiController
{
    private function read(Request $request, Server $server): void { abort_unless($request->user()->can(Permission::ACTION_FILE_READ, $server), 403); }
    private function write(Request $request, Server $server): void { $this->read($request, $server); abort_unless($request->user()->can(Permission::ACTION_FILE_UPDATE, $server) && $request->user()->can(Permission::ACTION_FILE_CREATE, $server), 403); }
    private function mutate(Server $server, \Closure $callback): mixed { $lock = Cache::lock("server-plugin-mutation:{$server->id}", 180); if (!$lock->get()) abort(409, 'Another plugin operation is already in progress.'); try { return $callback(); } finally { $lock->release(); } }
    public function search(Request $request, Server $server, ModrinthPluginService $service): array { $this->read($request, $server); return $service->search($server, $request->validate(['query' => 'nullable|string|max:100'])['query'] ?? ''); }
    public function installed(Request $request, Server $server, ModrinthPluginService $service): array { $this->read($request, $server); return $service->installed($server); }
    public function dependencies(Request $request, Server $server, string $project, ModrinthPluginService $service): array { $this->read($request, $server); return ['data' => $service->dependenciesFor($server, $project)]; }
    public function install(Request $request, Server $server, string $project, ModrinthPluginService $service): JsonResponse { $this->write($request, $server); $data = $request->validate(['dependencies' => 'array', 'dependencies.*' => 'string|max:32']); return $this->mutate($server, function () use ($service, $server, $project, $data) { $installed = $service->install($server, $project, $data['dependencies'] ?? []); Activity::event('server:plugin.install')->subject($server)->property('project_id', $project)->property('installed', $installed)->log(); return new JsonResponse(['data' => $installed, 'restart_required' => true], 201); }); }
    public function update(Request $request, Server $server, string $filename, ModrinthPluginService $service): JsonResponse { $this->write($request, $server); $data = $request->validate(['project_id' => 'required|string|max:32', 'dependencies' => 'array', 'dependencies.*' => 'string|max:32']); return $this->mutate($server, function () use ($service, $server, $filename, $data) { $installed = $service->update($server, $filename, $data['project_id'], $data['dependencies'] ?? []); Activity::event('server:plugin.update')->subject($server)->property('filename', $filename)->property('project_id', $data['project_id'])->log(); return new JsonResponse(['data' => $installed, 'restart_required' => true]); }); }
    public function toggle(Request $request, Server $server, string $filename, ModrinthPluginService $service): JsonResponse { $this->write($request, $server); $enable = $request->validate(['enable' => 'required|boolean'])['enable']; return $this->mutate($server, function () use ($service, $server, $filename, $enable) { $service->toggle($server, $filename, $enable); Activity::event($enable ? 'server:plugin.enable' : 'server:plugin.disable')->subject($server)->property('filename', $filename)->log(); return new JsonResponse(['restart_required' => true]); }); }
    public function remove(Request $request, Server $server, string $filename, ModrinthPluginService $service): JsonResponse { $this->read($request, $server); abort_unless($request->user()->can(Permission::ACTION_FILE_DELETE, $server), 403); return $this->mutate($server, function () use ($service, $server, $filename) { $service->remove($server, $filename); Activity::event('server:plugin.remove')->subject($server)->property('filename', $filename)->log(); return new JsonResponse([], 204); }); }
    public function download(Request $request, Server $server, string $project, ModrinthPluginService $service): RedirectResponse { $this->read($request, $server); return redirect()->away($service->downloadUrl($server, $project)); }
}
