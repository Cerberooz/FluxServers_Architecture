<?php

namespace Pterodactyl\Http\Controllers\Api\Client\Servers;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Pterodactyl\Facades\Activity;
use Pterodactyl\Models\Permission;
use Pterodactyl\Models\Server;
use Pterodactyl\Models\ServerSubdomain;
use Pterodactyl\Models\SubdomainDomain;
use Pterodactyl\Jobs\Subdomains\SyncServerSubdomainJob;
use Pterodactyl\Jobs\Subdomains\DeleteServerSubdomainJob;
use Pterodactyl\Services\Subdomains\SubdomainDnsService;
use Pterodactyl\Http\Controllers\Api\Client\ClientApiController;

class SubdomainController extends ClientApiController
{
    public function index(Request $request, Server $server): array
    {
        abort_unless($request->user()->can(Permission::ACTION_ALLOCATION_READ, $server), 403);
        return ['data' => $server->subdomains()->with('domain')->get()->map(fn (ServerSubdomain $s) => $this->payload($s))->values()];
    }

    public function domains(Request $request, Server $server): array
    {
        abort_unless($request->user()->can(Permission::ACTION_ALLOCATION_READ, $server), 403);
        return ['data' => SubdomainDomain::query()->where('enabled', true)->get()->filter(fn (SubdomainDomain $d) => empty($d->allowed_egg_ids) || in_array($server->egg_id, $d->allowed_egg_ids, true))->map(fn (SubdomainDomain $d) => ['id' => $d->id, 'domain' => $d->domain, 'max_per_server' => $d->max_per_server])->values()];
    }

    public function store(Request $request, Server $server, SubdomainDnsService $service): JsonResponse
    {
        abort_unless($request->user()->can(Permission::ACTION_ALLOCATION_READ, $server), 403);
        $data = $request->validate(['domain_id' => 'required|integer|exists:subdomain_domains,id', 'label' => 'required|string|max:63']);
        $subdomain = $service->create($server, SubdomainDomain::findOrFail($data['domain_id']), $data['label']);
        SyncServerSubdomainJob::dispatch($subdomain);
        Activity::event('server:subdomain.create')->subject($server, $subdomain)->property('hostname', $subdomain->hostname)->log();
        return new JsonResponse(['object' => 'subdomain', 'attributes' => $this->payload($subdomain)], 202);
    }

    public function destroy(Request $request, Server $server, ServerSubdomain $subdomain): JsonResponse
    {
        abort_unless($subdomain->server_id === $server->id && $request->user()->can(Permission::ACTION_ALLOCATION_READ, $server), 403);
        $subdomain->forceFill(['status' => ServerSubdomain::STATUS_DELETING, 'last_error' => null])->save();
        DeleteServerSubdomainJob::dispatch($subdomain);
        Activity::event('server:subdomain.delete')->subject($server, $subdomain)->property('hostname', $subdomain->hostname)->log();
        return new JsonResponse([], 202);
    }

    public function update(Request $request, Server $server, ServerSubdomain $subdomain, SubdomainDnsService $service): JsonResponse
    {
        abort_unless($subdomain->server_id === $server->id && $request->user()->can(Permission::ACTION_ALLOCATION_READ, $server), 403);
        $data = $request->validate(['label' => 'required|string|max:63']);
        $subdomain = $service->rename($subdomain, $data['label']);
        SyncServerSubdomainJob::dispatch($subdomain);
        Activity::event('server:subdomain.rename')->subject($server, $subdomain)->property('hostname', $subdomain->hostname)->log();
        return new JsonResponse(['object' => 'subdomain', 'attributes' => $this->payload($subdomain)], 202);
    }

    private function payload(ServerSubdomain $subdomain): array
    {
        return ['id' => $subdomain->id, 'hostname' => $subdomain->hostname, 'status' => $subdomain->status, 'last_error' => $subdomain->last_error, 'port' => $subdomain->target_port, 'connection_address' => $subdomain->target_port && $subdomain->target_port !== 25565 ? $subdomain->hostname : $subdomain->hostname];
    }
}
