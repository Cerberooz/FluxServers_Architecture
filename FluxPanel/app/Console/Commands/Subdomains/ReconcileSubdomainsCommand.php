<?php

namespace Pterodactyl\Console\Commands\Subdomains;

use Illuminate\Console\Command;
use Pterodactyl\Jobs\Subdomains\DeleteServerSubdomainJob;
use Pterodactyl\Jobs\Subdomains\SyncServerSubdomainJob;
use Pterodactyl\Models\ServerSubdomain;

class ReconcileSubdomainsCommand extends Command
{
    protected $signature = 'p:subdomains:reconcile';
    protected $description = 'Queue reconciliation of customer subdomain DNS records.';

    public function handle(): int
    {
        $count = 0;
        ServerSubdomain::query()->whereIn('status', ['pending', 'active', 'updating', 'error'])->cursor()->each(function (ServerSubdomain $subdomain) use (&$count) {
            SyncServerSubdomainJob::dispatch($subdomain);
            ++$count;
        });
        ServerSubdomain::query()->where('status', ServerSubdomain::STATUS_DELETING)->cursor()->each(function (ServerSubdomain $subdomain) use (&$count) {
            DeleteServerSubdomainJob::dispatch($subdomain);
            ++$count;
        });
        $this->info("Queued reconciliation for {$count} subdomain(s).");
        return self::SUCCESS;
    }
}
