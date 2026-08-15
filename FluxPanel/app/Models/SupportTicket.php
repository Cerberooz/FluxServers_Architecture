<?php

namespace Pterodactyl\Models;

use Illuminate\Database\Eloquent\Relations\BelongsTo;

class SupportTicket extends Model
{
    public const STATUS_OPEN = 'open';
    public const STATUS_IN_PROGRESS = 'in_progress';
    public const STATUS_RESOLVED = 'resolved';

    protected $table = 'support_tickets';
    protected $guarded = ['id', 'created_at', 'updated_at'];

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }
}
