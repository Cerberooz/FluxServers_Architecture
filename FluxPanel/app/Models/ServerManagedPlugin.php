<?php
namespace Pterodactyl\Models;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
class ServerManagedPlugin extends Model { protected $guarded = ['id']; protected $casts = ['disabled' => 'boolean']; public function server(): BelongsTo { return $this->belongsTo(Server::class); } }
