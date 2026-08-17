<?php

namespace Pterodactyl\Http\Controllers\Api\Client\Servers;

use Illuminate\Http\Request;
use Pterodactyl\Http\Controllers\Api\Client\ClientApiController;
use Pterodactyl\Models\Permission;
use Pterodactyl\Models\Server;
use Pterodactyl\Services\Plugins\ModrinthPluginService;

class RuntimeMetadataController extends ClientApiController
{
    public function __invoke(Request $request, Server $server, ModrinthPluginService $plugins): array
    {
        abort_unless($request->user()->can(Permission::ACTION_FILE_READ, $server), 403);

        return ['attributes' => $plugins->runtimeMetadata($server)];
    }
}
