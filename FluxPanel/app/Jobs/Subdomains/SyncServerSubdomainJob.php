<?php

namespace Pterodactyl\Jobs\Subdomains;

use Illuminate\Bus\Queueable;
use Illuminate\Queue\SerializesModels;
use Illuminate\Contracts\Queue\ShouldQueue;
use Pterodactyl\Models\ServerSubdomain;
use Pterodactyl\Services\Subdomains\SubdomainDnsService;

class SyncServerSubdomainJob implements ShouldQueue
{
    use Queueable, SerializesModels;
    public int $tries = 5;
    public array $backoff = [10, 60, 300, 900];
    public function __construct(public ServerSubdomain $subdomain) { $this->queue = 'standard'; }
    public function handle(SubdomainDnsService $service): void
    {
        if ($subdomain = $this->subdomain->fresh()) {
            $service->sync($subdomain);
        }
    }
}
