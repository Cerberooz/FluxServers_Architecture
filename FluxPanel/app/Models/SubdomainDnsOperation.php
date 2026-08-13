<?php

namespace Pterodactyl\Models;

use Illuminate\Database\Eloquent\Relations\BelongsTo;

class SubdomainDnsOperation extends Model
{
    protected $table = 'subdomain_dns_operations';
    protected $guarded = ['id', 'created_at', 'updated_at'];
    protected $casts = ['subdomain_id' => 'integer', 'attempt' => 'integer', 'context' => 'array'];

    public function subdomain(): BelongsTo { return $this->belongsTo(ServerSubdomain::class, 'subdomain_id'); }
}
