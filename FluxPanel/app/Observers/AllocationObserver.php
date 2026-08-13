<?php

namespace Pterodactyl\Observers;

use Pterodactyl\Models\Allocation;
use Pterodactyl\Jobs\Subdomains\SyncServerSubdomainJob;

class AllocationObserver
{
    public function updated(Allocation $allocation): void
    {
        if ($allocation->server_id && $allocation->wasChanged(['ip', 'port'])) {
            $allocation->server?->subdomains()->each(fn ($subdomain) => SyncServerSubdomainJob::dispatch($subdomain));
        }
    }
}
