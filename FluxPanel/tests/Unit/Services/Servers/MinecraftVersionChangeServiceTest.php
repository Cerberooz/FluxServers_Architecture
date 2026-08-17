<?php

namespace Pterodactyl\Tests\Unit\Services\Servers;

use Illuminate\Database\ConnectionInterface;
use Illuminate\Database\Eloquent\Collection as EloquentCollection;
use Illuminate\Support\Facades\Http;
use Pterodactyl\Models\Egg;
use Pterodactyl\Models\EggVariable;
use Pterodactyl\Repositories\Wings\DaemonFileRepository;
use Pterodactyl\Repositories\Wings\DaemonServerRepository;
use Pterodactyl\Services\Servers\MinecraftVersionChangeService;
use Pterodactyl\Services\Servers\ReinstallServerService;
use Pterodactyl\Services\Servers\VariableValidatorService;
use Pterodactyl\Tests\TestCase;

class MinecraftVersionChangeServiceTest extends TestCase
{
    private function service(): MinecraftVersionChangeService
    {
        return new MinecraftVersionChangeService(
            \Mockery::mock(ConnectionInterface::class),
            \Mockery::mock(VariableValidatorService::class),
            \Mockery::mock(ReinstallServerService::class),
            \Mockery::mock(DaemonFileRepository::class),
            \Mockery::mock(DaemonServerRepository::class),
        );
    }

    public function testItOnlyClassifiesSupportedEggsAndExtractsValidatedVersionChoices(): void
    {
        $service = $this->service();
        $method = new \ReflectionMethod($service, 'eggOption');

        $egg = new Egg(['name' => 'Paper Minecraft']);
        $egg->id = 42;
        $egg->setRelation('variables', new EloquentCollection([
            new EggVariable([
                'env_variable' => 'MINECRAFT_VERSION',
                'default_value' => '1.21.11',
                'rules' => 'required|string|in:1.21.8,1.21.11',
            ]),
            new EggVariable([
                'env_variable' => 'BUILD_NUMBER',
                'default_value' => '128',
                'rules' => 'required|integer|in:127,128',
            ]),
        ]));

        $option = $method->invoke($service, $egg);

        $this->assertSame('Paper', $option['platform']);
        $this->assertSame(['1.21.11', '1.21.8'], $option['versions']);
        $this->assertSame(['128', '127'], $option['builds']);
        $this->assertFalse($option['custom_version_allowed']);
    }

    public function testItRecognisesProxyEggsButLeavesUnrecognisedEggsUnavailable(): void
    {
        $service = $this->service();
        $method = new \ReflectionMethod($service, 'eggOption');

        $velocity = new Egg(['name' => 'Velocity Proxy']);
        $velocity->setRelation('variables', new EloquentCollection());
        $unknown = new Egg(['name' => 'Generic Java']);
        $unknown->setRelation('variables', new EloquentCollection());

        $this->assertSame('Velocity', $method->invoke($service, $velocity)['platform']);
        $this->assertNull($method->invoke($service, $unknown));
    }

    public function testItRecognisesPlatformSpecificVersionVariableNames(): void
    {
        $service = $this->service();
        $method = new \ReflectionMethod($service, 'versionVariable');
        $variables = new EloquentCollection([
            new EggVariable(['env_variable' => 'VANILLA_VERSION']),
            new EggVariable(['env_variable' => 'FORGE_VERSION']),
        ]);

        $this->assertSame('VANILLA_VERSION', $method->invoke($service, $variables)->env_variable);
    }

    public function testItExpandsACustomPaperVersionVariableWithTheOfficialCatalogue(): void
    {
        Http::fake([
            'https://fill.papermc.io/v3/projects/paper' => Http::response([
                'versions' => ['1.21' => ['1.21.11', '1.21.10'], 'legacy' => ['not-a-release']],
            ]),
        ]);

        $service = $this->service();
        $method = new \ReflectionMethod($service, 'eggOption');
        $egg = new Egg(['name' => 'Paper Minecraft']);
        $egg->id = 77;
        $egg->setRelation('variables', new EloquentCollection([
            new EggVariable([
                'env_variable' => 'VERSION',
                'default_value' => 'latest',
                'rules' => 'required|string|max:32',
            ]),
        ]));

        $option = $method->invoke($service, $egg);

        $this->assertSame(['latest', '1.21.11', '1.21.10'], $option['versions']);
        $this->assertTrue($option['custom_version_allowed']);
    }
}
