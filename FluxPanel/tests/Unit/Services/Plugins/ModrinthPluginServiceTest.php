<?php

namespace Pterodactyl\Tests\Unit\Services\Plugins;

use Illuminate\Support\Collection;
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
