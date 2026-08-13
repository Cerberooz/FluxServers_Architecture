<?php

namespace Pterodactyl\Models;

use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class ServerSubdomain extends Model
{
    public const STATUS_PENDING = 'pending';
    public const STATUS_ACTIVE = 'active';
    public const STATUS_UPDATING = 'updating';
    public const STATUS_DELETING = 'deleting';
    public const STATUS_ERROR = 'error';

    protected $table = 'server_subdomains';
    protected $guarded = ['id', 'created_at', 'updated_at'];
    protected $casts = ['server_id' => 'integer', 'domain_id' => 'integer', 'allocation_id' => 'integer', 'target_port' => 'integer', 'last_synced_at' => 'datetime'];

    public function server(): BelongsTo { return $this->belongsTo(Server::class); }
    public function domain(): BelongsTo { return $this->belongsTo(SubdomainDomain::class, 'domain_id'); }
    public function operations(): HasMany { return $this->hasMany(SubdomainDnsOperation::class, 'subdomain_id'); }
}
