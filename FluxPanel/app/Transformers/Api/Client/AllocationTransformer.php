<?php

namespace Pterodactyl\Transformers\Api\Client;

use Pterodactyl\Models\Allocation;
use Pterodactyl\Services\Servers\PublicMinecraftAddressService;

class AllocationTransformer extends BaseClientTransformer
{
    /**
     * Return the resource name for the JSONAPI output.
     */
    public function getResourceName(): string
    {
        return 'allocation';
    }

    public function transform(Allocation $model): array
    {
        $public = app(PublicMinecraftAddressService::class);
        // Customer views should use the allocation alias when the administrator
        // configured one. The public host remains a safe fallback for legacy
        // allocations so an origin node IP is never exposed.
        $host = $model->ip_alias ?: $public->host();

        return [
            'id' => $model->id,
            // Never expose the origin allocation IP through customer endpoints.
            'ip' => $host,
            'ip_alias' => $model->ip_alias,
            'port' => $model->port,
            'address' => sprintf('%s:%d', $host, $model->port),
            'notes' => $model->notes,
            'is_default' => $model->server->allocation_id === $model->id,
        ];
    }
}
