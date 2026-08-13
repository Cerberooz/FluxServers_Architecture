<?php
namespace Pterodactyl\Models;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
class ServerOptimizerFinding extends Model {
    protected $guarded = ['id'];
    protected $casts = ['evidence' => 'array', 'recommendation' => 'array', 'gameplay_change' => 'boolean', 'restart_required' => 'boolean', 'ignored' => 'boolean'];
    public function run(): BelongsTo { return $this->belongsTo(ServerOptimizerRun::class, 'run_id'); }
}
