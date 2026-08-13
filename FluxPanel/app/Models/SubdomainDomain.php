<?php

namespace Pterodactyl\Models;

use Illuminate\Database\Eloquent\Relations\HasMany;

class SubdomainDomain extends Model
{
    protected $table = 'subdomain_domains';
    protected $guarded = ['id', 'created_at', 'updated_at'];
    protected $casts = ['enabled' => 'boolean', 'allowed_egg_ids' => 'array', 'reserved_labels' => 'array'];

    public function subdomains(): HasMany
    {
        return $this->hasMany(ServerSubdomain::class, 'domain_id');
    }
}
