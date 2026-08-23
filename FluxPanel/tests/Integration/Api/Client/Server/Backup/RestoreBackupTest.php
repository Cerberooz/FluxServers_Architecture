<?php

namespace Pterodactyl\Tests\Integration\Api\Client\Server\Backup;

use Mockery\MockInterface;
use Carbon\CarbonImmutable;
use Illuminate\Http\Response;
use Pterodactyl\Models\Backup;
use Pterodactyl\Models\Permission;
use GuzzleHttp\Psr7\Response as GuzzleResponse;
use Pterodactyl\Repositories\Wings\DaemonBackupRepository;
use Pterodactyl\Tests\Integration\Api\Client\ClientApiIntegrationTestCase;

class RestoreBackupTest extends ClientApiIntegrationTestCase
{
    private MockInterface $repository;

    public function setUp(): void
    {
        parent::setUp();

        $this->repository = $this->mock(DaemonBackupRepository::class);
    }

    public function testBackupCanBeRestored()
    {
        [$user, $server] = $this->generateTestAccount([Permission::ACTION_BACKUP_RESTORE]);

        /** @var Backup $backup */
        $backup = Backup::factory()->create(['server_id' => $server->id, 'node_id' => $server->node_id]);

        $this->repository->expects('setServer->restore')->with(
            \Mockery::on(function ($value) use ($backup) {
                return $value instanceof Backup && $value->uuid === $backup->uuid;
            }),
            null,
            true,
        )->andReturn(new GuzzleResponse());

        $this->actingAs($user)->postJson($this->link($backup, 'restore'), ['truncate' => true])
            ->assertStatus(Response::HTTP_NO_CONTENT);
    }

    public function testBackupCannotBeRestoredFromAnotherNode()
    {
        [$user, $server] = $this->generateTestAccount([Permission::ACTION_BACKUP_RESTORE]);

        $backup = Backup::factory()->create(['server_id' => $server->id, 'node_id' => $server->node_id + 1]);

        $this->repository->shouldNotReceive('setServer');

        $this->actingAs($user)->postJson($this->link($backup, 'restore'), ['truncate' => true])
            ->assertStatus(Response::HTTP_BAD_REQUEST)
            ->assertJsonPath('errors.0.detail', 'This node-local backup is stored on a different node and cannot be restored or downloaded from this server.');
    }

    public function testLegacyNodeLocalBackupCannotBeRestored()
    {
        [$user, $server] = $this->generateTestAccount([Permission::ACTION_BACKUP_RESTORE]);

        $backup = Backup::factory()->create(['server_id' => $server->id, 'node_id' => null]);

        $this->repository->shouldNotReceive('setServer');

        $this->actingAs($user)->postJson($this->link($backup, 'restore'), ['truncate' => true])
            ->assertStatus(Response::HTTP_BAD_REQUEST)
            ->assertJsonPath('errors.0.detail', 'This node-local backup was created before its source node was recorded and cannot be restored safely.');
    }

    #[\PHPUnit\Framework\Attributes\DataProvider('invalidBackupDataProvider')]
    public function testBackupCannotBeRestoredUntilSuccessfulAndComplete(bool $isSuccessful, bool $isCompleted)
    {
        [$user, $server] = $this->generateTestAccount([Permission::ACTION_BACKUP_RESTORE]);

        /** @var Backup $backup */
        $backup = Backup::factory()->create([
            'server_id' => $server->id,
            'node_id' => $server->node_id,
            'is_successful' => $isSuccessful,
            'completed_at' => $isCompleted ? CarbonImmutable::now() : null,
        ]);

        $this->repository->shouldNotReceive('setServer');

        $this->actingAs($user)->postJson($this->link($backup, 'restore'), ['truncate' => true])
            ->assertStatus(Response::HTTP_BAD_REQUEST);
    }

    public static function invalidBackupDataProvider(): array
    {
        return [
            'failed completed' => [false, true],
            'failed incomplete' => [false, false],
            'successful incomplete' => [true, false],
        ];
    }
}
