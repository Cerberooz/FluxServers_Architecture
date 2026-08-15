<?php

namespace Pterodactyl\Services\Servers;

use Pterodactyl\Models\Allocation;

class PublicMinecraftAddressService
{
    public function host(): string
    {
        return rtrim((string) (config('pterodactyl.minecraft_public_host') ?: 'play.fluxservers.cloud'), '.');
    }

    public function address(Allocation $allocation): string
    {
        return sprintf('%s:%d', $this->host(), $allocation->port);
    }
}
