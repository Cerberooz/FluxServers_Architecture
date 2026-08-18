<?php

namespace Pterodactyl\Tests\Unit\Services\Plugins;

use Illuminate\Support\Collection;
use Illuminate\Support\Facades\Http;
use Pterodactyl\Exceptions\DisplayException;
use Pterodactyl\Models\Egg;
use Pterodactyl\Models\EggVariable;
use Pterodactyl\Models\Nest;
use Pterodactyl\Models\Server;
use Pterodactyl\Repositories\Wings\DaemonFileRepository;
use Pterodactyl\Services\Plugins\ModrinthPluginService;
use Pterodactyl\Tests\TestCase;

class ModrinthPluginServiceTest extends TestCase
{
    private function service(): ModrinthPluginService
    {
        return new ModrinthPluginService(\Mockery::mock(DaemonFileRepository::class));
    }

    public function testItRejectsTraversalPluginFilenames(): void
    {
        $method = new \ReflectionMethod($this->service(), 'filename');
        $this->expectException(DisplayException::class);
        $method->invoke($this->service(), '../outside.jar');
    }

    public function testItOnlyAcceptsModrinthCdnDownloads(): void
    {
        $method = new \ReflectionMethod($this->service(), 'cdn');
        $this->assertSame('https://cdn.modrinth.com/data/project/versions/version/plugin.jar', $method->invoke($this->service(), 'https://cdn.modrinth.com/data/project/versions/version/plugin.jar'));
        $this->expectException(DisplayException::class);
        $method->invoke($this->service(), 'https://example.com/plugin.jar');
    }

    public function testItPrefersPrimaryJarFiles(): void
    {
        $method = new \ReflectionMethod($this->service(), 'primaryFile');
        $file = $method->invoke($this->service(), ['files' => [
            ['filename' => 'sources.jar', 'primary' => false],
            ['filename' => 'plugin.jar', 'primary' => true],
        ]]);
        $this->assertSame('plugin.jar', $file['filename']);
    }

    public function testItDetectsPurpurAndMinecraftVersionFromTheServerEgg(): void
    {
        $server = new Server();
        $server->setRelation('egg', new Egg(['name' => 'Purpur Minecraft']));
        $server->setRelation('nest', new Nest(['name' => 'Minecraft']));
        $server->setRelation('variables', new Collection([new EggVariable(['name' => 'Minecraft Version', 'server_value' => '1.21.4'])]));

        $context = $this->service()->context($server);

        $this->assertTrue($context['supported']);
        $this->assertSame('purpur', $context['platform']);
        $this->assertSame('1.21.4', $context['version']);
        $this->assertContains('paper', $context['loaders']);
    }

    public function testItMarksUnknownServerSoftwareAsUnsupported(): void
    {
        $server = new Server();
        $server->setRelation('egg', new Egg(['name' => 'Forge 1.21.4']));
        $server->setRelation('nest', new Nest(['name' => 'Minecraft']));
        $server->setRelation('variables', new Collection());

        $this->assertFalse($this->service()->context($server)['supported']);
    }

    public function testItPrefersAPaperStartupSignatureOverAnUnrelatedVelocityLogMention(): void
    {
        $method = new \ReflectionMethod($this->service(), 'runtimeSoftware');
        $log = "[INFO]: loaded VelocitySupport plugin\n[INFO]: This server is running Paper version 1.21.11-132-ver/1.21.11";

        $this->assertSame('Paper', $method->invoke($this->service(), $log));
    }

    public function testItRecognisesModernPaperAndFoliaBootstrapLogLines(): void
    {
        $service = $this->service();
        $software = new \ReflectionMethod($service, 'runtimeSoftware');
        $version = new \ReflectionMethod($service, 'runtimeMinecraftVersion');

        $paper = '[ServerMain/INFO]: Loading Minecraft 1.21.8 with Paper';
        $folia = '[ServerMain/INFO]: Loading Minecraft 1.21.4 with Folia';

        $this->assertSame('Paper', $software->invoke($service, $paper));
        $this->assertSame('1.21.8', $version->invoke($service, $paper));
        $this->assertSame('Folia', $software->invoke($service, $folia));
        $this->assertSame('1.21.4', $version->invoke($service, $folia));
    }

    public function testRuntimeMetadataStreamsTheStartupLogPrefix(): void
    {
        $files = \Mockery::mock(DaemonFileRepository::class);
        $files->expects('setServer')->andReturnSelf();
        $files->expects('getContentPrefix')
            ->with('logs/latest.log', 1048576)
            ->andReturn('[ServerMain/INFO]: Loading Minecraft 1.21.8 with Paper');
        $service = new ModrinthPluginService($files);
        $server = new Server();
        $server->forceFill(['id' => 987654]);
        $server->setRelation('egg', new Egg(['name' => 'Minecraft Java']));
        $server->setRelation('nest', new Nest(['name' => 'Minecraft']));
        $server->setRelation('variables', new Collection());

        $metadata = $service->runtimeMetadata($server);

        $this->assertSame('1.21.8', $metadata['minecraft_version']);
        $this->assertSame('Paper', $metadata['software']);
        $this->assertSame('runtime_log', $metadata['source']);
    }

    public function testRuntimeMetadataFallsBackToConcreteEggConfiguration(): void
    {
        $files = \Mockery::mock(DaemonFileRepository::class);
        $files->allows('setServer')->andReturnSelf();
        $files->allows('getContentPrefix')->andThrow(new \RuntimeException('latest.log unavailable'));
        $service = new ModrinthPluginService($files);
        $server = new Server();
        $server->setRelation('egg', new Egg(['name' => 'Purpur 1.21.4']));
        $server->setRelation('nest', new Nest(['name' => 'Minecraft']));
        $server->setRelation('variables', new Collection());

        $metadata = $service->runtimeMetadata($server);

        $this->assertSame('1.21.4', $metadata['minecraft_version']);
        $this->assertSame('Purpur', $metadata['software']);
        $this->assertSame('configuration', $metadata['source']);
    }

    public function testCompatibleReleaseDoesNotHaveToBeFeatured(): void
    {
        Http::fake([
            'api.modrinth.com/*' => Http::response([[
                'id' => 'version-id',
                'project_id' => 'project-id',
                'featured' => false,
                'files' => [['filename' => 'plugin.jar']],
            ]]),
        ]);
        $service = $this->service();
        $method = new \ReflectionMethod($service, 'resolveCompatibleVersion');

        $release = $method->invoke($service, 'project-id', [
            'loaders' => ['paper', 'spigot', 'bukkit'],
            'version' => '1.21.4',
        ]);

        $this->assertSame('version-id', $release['id']);
        Http::assertSent(fn ($request) => !str_contains($request->url(), 'featured='));
    }

    public function testItRecognisesVelocityOnlyFromAnActualStartupSignature(): void
    {
        $method = new \ReflectionMethod($this->service(), 'runtimeSoftware');

        $this->assertSame('Velocity', $method->invoke($this->service(), 'This server is running Velocity version 3.4.0'));
        $this->assertNull($method->invoke($this->service(), 'VelocitySupport plugin enabled'));
    }

    public function testItRejectsInvalidModrinthProjectIdentifiers(): void
    {
        $method = new \ReflectionMethod($this->service(), 'projectId');
        $this->expectException(DisplayException::class);
        $method->invoke($this->service(), '../project');
    }
}
