<?php

namespace Pterodactyl\Models;

use Illuminate\Database\Eloquent\SoftDeletes;
use Pterodactyl\Contracts\Models\Identifiable;
use Pterodactyl\Models\Traits\HasRealtimeIdentifier;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Factories\HasFactory;

/**
 * @property int $id
 * @property int $server_id
 * @property int|null $node_id
 * @property string $uuid
 * @property bool $is_successful
 * @property bool $is_locked
 * @property string $name
 * @property string[] $ignored_files
 * @property string $disk
 * @property string|null $checksum
 * @property int $bytes
 * @property string|null $upload_id
 * @property \Carbon\CarbonImmutable|null $completed_at
 * @property \Carbon\CarbonImmutable $created_at
 * @property \Carbon\CarbonImmutable $updated_at
 * @property \Carbon\CarbonImmutable|null $deleted_at
 * @property Server $server
 * @property \Pterodactyl\Models\AuditLog[] $audits
 */
#[Attributes\Identifiable('bkup')]
class Backup extends Model implements Identifiable
{
    /** @use HasFactory<\Database\Factories\BackupFactory> */
    use HasFactory;
    use SoftDeletes;
    use HasRealtimeIdentifier;

    public const RESOURCE_NAME = 'backup';

    public const ADAPTER_WINGS = 'wings';
    public const ADAPTER_AWS_S3 = 's3';

    protected $table = 'backups';

    protected bool $immutableDates = true;

    protected $casts = [
        'id' => 'int',
        'node_id' => 'int',
        'is_successful' => 'bool',
        'is_locked' => 'bool',
        'ignored_files' => 'array',
        'bytes' => 'int',
        'completed_at' => 'datetime',
    ];

    protected $attributes = [
        'is_successful' => false,
        'is_locked' => false,
        'checksum' => null,
        'bytes' => 0,
        'upload_id' => null,
    ];

    protected $guarded = ['id', 'created_at', 'updated_at', 'deleted_at'];

    public static array $validationRules = [
        'server_id' => 'bail|required|numeric|exists:servers,id',
        'node_id' => 'nullable|numeric|exists:nodes,id',
        'uuid' => 'required|uuid',
        'is_successful' => 'boolean',
        'is_locked' => 'boolean',
        'name' => 'required|string',
        'ignored_files' => 'array',
        'disk' => 'required|string',
        'checksum' => 'nullable|string',
        'bytes' => 'numeric',
        'upload_id' => 'nullable|string',
    ];

    /**
     * @return \Illuminate\Database\Eloquent\Relations\BelongsTo<\Pterodactyl\Models\Server, $this>
     */
    public function server(): BelongsTo
    {
        return $this->belongsTo(Server::class);
    }

    /**
     * Wings backups live on the node that created them. Unlike S3 backups, Wings
     * cannot restore or download an archive after the server has moved to another
     * node. A missing node id is treated as unavailable so legacy records cannot
     * accidentally trigger a destructive restore on a different node.
     */
    public function availabilityReasonForNode(?int $nodeId): ?string
    {
        if ($this->disk === self::ADAPTER_AWS_S3) {
            return null;
        }

        if ($this->disk !== self::ADAPTER_WINGS) {
            return 'This backup uses an unsupported storage adapter and cannot be restored safely.';
        }

        if (is_null($this->node_id)) {
            return 'This node-local backup was created before its source node was recorded and cannot be restored safely.';
        }

        if (is_null($nodeId) || $this->node_id !== $nodeId) {
            return 'This node-local backup is stored on a different node and cannot be restored or downloaded from this server.';
        }

        return null;
    }

    public function isAvailableOnNode(?int $nodeId): bool
    {
        return is_null($this->availabilityReasonForNode($nodeId));
    }
}
