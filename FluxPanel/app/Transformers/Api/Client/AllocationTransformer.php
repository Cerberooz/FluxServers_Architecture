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

        return [
            'id' => $model->id,
            // Never expose the origin allocation IP through customer endpoints.
            'ip' => $public->host(),
            'ip_alias' => null,
            'port' => $model->port,
            'address' => $public->address($model),
            'notes' => $model->notes,
            'is_default' => $model->server->allocation_id === $model->id,
        ];
    }
}
