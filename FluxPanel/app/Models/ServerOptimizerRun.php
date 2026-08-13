<?php
namespace Pterodactyl\Models;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
class ServerOptimizerRun extends Model {
    protected $guarded = ['id'];
    protected $casts = ['summary' => 'array', 'started_at' => 'datetime', 'completed_at' => 'datetime'];
    public function server(): BelongsTo { return $this->belongsTo(Server::class); }
    public function findings(): HasMany { return $this->hasMany(ServerOptimizerFinding::class, 'run_id'); }
}
