<?php

namespace Pterodactyl\Http\Controllers\Api\Client\Servers;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Pterodactyl\Facades\Activity;
use Pterodactyl\Http\Controllers\Api\Client\ClientApiController;
use Pterodactyl\Models\Permission;
use Pterodactyl\Models\Server;
use Pterodactyl\Services\Servers\MinecraftVersionChangeService;

class VersionChangerController extends ClientApiController
{
    private function authorize(Request $request, Server $server): void
    {
        abort_unless(
            $request->user()->can(Permission::ACTION_SETTINGS_REINSTALL, $server)
            && $request->user()->can(Permission::ACTION_STARTUP_UPDATE, $server),
            403
        );
    }

    public function index(Request $request, Server $server, MinecraftVersionChangeService $service): array
    {
        $this->authorize($request, $server);

        return ['attributes' => $service->options($server)];
    }

    public function install(Request $request, Server $server, MinecraftVersionChangeService $service): JsonResponse
    {
        $this->authorize($request, $server);
        $data = $request->validate([
            'egg_id' => ['required', 'integer', 'exists:eggs,id'],
            'version' => ['nullable', 'string', 'max:64'],
            'build' => ['nullable', 'string', 'max:64'],
            'wipe' => ['required', 'boolean'],
            'confirm' => ['accepted'],
        ]);

        $changed = $service->change($server, $data);
        Activity::event('server:version-changer.install')
            ->subject($changed)
            ->property(['egg_id' => $data['egg_id'], 'version' => $data['version'] ?? null, 'build' => $data['build'] ?? null, 'wiped' => $data['wipe']])
            ->log();

        return new JsonResponse(['attributes' => ['status' => $changed->status]], JsonResponse::HTTP_ACCEPTED);
    }
}
