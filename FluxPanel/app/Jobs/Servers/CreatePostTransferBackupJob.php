<?php

namespace Pterodactyl\Jobs\Servers;

use Illuminate\Bus\Queueable;
use Illuminate\Support\Facades\Log;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Bus\Dispatchable;
use Illuminate\Queue\InteractsWithQueue;
use Illuminate\Queue\SerializesModels;
use Pterodactyl\Models\Server;
use Pterodactyl\Models\ServerTransfer;
use Pterodactyl\Services\Backups\InitiateBackupService;

class CreatePostTransferBackupJob implements ShouldQueue
{
    use Dispatchable;
    use InteractsWithQueue;
    use Queueable;
    use SerializesModels;

    public int $tries = 1;

    public function __construct(public int $serverId, public int $transferId)
    {
        $this->queue = 'standard';
    }

    /**
     * Create a new, independent archive on the destination node after Wings has
     * confirmed that the server transfer completed. Existing source-node backups
     * are never changed or deleted by this job.
     */
    public function handle(InitiateBackupService $backupService): void
    {
        $transfer = ServerTransfer::query()->find($this->transferId);
        $server = Server::query()->find($this->serverId);

        if (
            is_null($transfer)
            || is_null($server)
            || !$transfer->successful
            || $server->node_id !== $transfer->new_node
            || !is_null($server->status)
        ) {
            Log::warning('Skipped post-transfer safety backup because the server is not ready on the destination node.', [
                'server_id' => $this->serverId,
                'transfer_id' => $this->transferId,
            ]);

            return;
        }

        try {
            // Do not override the server backup limit. A safety copy must never
            // evict an existing backup in order to make room for itself.
            $backupService->handle(
                $server,
                sprintf('Post-transfer safety backup %s', now()->toDateTimeString()),
            );
        } catch (\Throwable $exception) {
            // A transfer is already complete; failing to create an additional
            // safety backup must not make it retry and create duplicate archives.
            Log::warning('Unable to create post-transfer safety backup.', [
                'server_id' => $this->serverId,
                'transfer_id' => $this->transferId,
                'exception' => $exception,
            ]);
        }
    }
}
