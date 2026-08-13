<?php
namespace Pterodactyl\Models;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
class ServerOptimizerSnapshot extends Model {
    protected $guarded = ['id'];
    protected $casts = ['restored_at' => 'datetime'];
    public function server(): BelongsTo { return $this->belongsTo(Server::class); }
    public function finding(): BelongsTo { return $this->belongsTo(ServerOptimizerFinding::class, 'finding_id'); }
}
