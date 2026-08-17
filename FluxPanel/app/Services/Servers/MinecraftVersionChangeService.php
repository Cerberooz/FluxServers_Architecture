<?php

namespace Pterodactyl\Services\Servers;

use Illuminate\Database\ConnectionInterface;
use Illuminate\Support\Arr;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use Pterodactyl\Exceptions\DisplayException;
use Pterodactyl\Exceptions\Http\Connection\DaemonConnectionException;
use Pterodactyl\Models\Egg;
use Pterodactyl\Models\EggVariable;
use Pterodactyl\Models\Server;
use Pterodactyl\Models\ServerVariable;
use Pterodactyl\Repositories\Wings\DaemonFileRepository;
use Pterodactyl\Repositories\Wings\DaemonServerRepository;
use Pterodactyl\Models\User;

/**
 * Changes a Minecraft server between explicitly imported Panel eggs.
 *
 * This deliberately never downloads a jar directly from the browser. Each selected
 * platform is an Egg the administrator has imported and vetted, so its install script,
 * container image, and validation rules remain the source of truth.
 */
class MinecraftVersionChangeService
{
    private const PLATFORMS = [
        'Paper' => ['pattern' => '/\\bpaper\\b/i', 'kind' => 'server', 'description' => 'High-performance Minecraft server software'],
        'Purpur' => ['pattern' => '/\\bpurpur\\b/i', 'kind' => 'server', 'description' => 'Paper fork with extensive configuration options'],
        'Folia' => ['pattern' => '/\\bfolia\\b/i', 'kind' => 'server', 'description' => 'Regionised multithreaded Paper fork'],
        'Pufferfish' => ['pattern' => '/\\bpufferfish\\b/i', 'kind' => 'server', 'description' => 'Performance-focused Paper fork'],
        'Leaf' => ['pattern' => '/\\bleaf\\b/i', 'kind' => 'server', 'description' => 'Performance-focused Paper fork'],
        'Vanilla' => ['pattern' => '/\\bvanilla\\b/i', 'kind' => 'server', 'description' => 'Official Minecraft server'],
        'Spigot' => ['pattern' => '/\\bspigot\\b/i', 'kind' => 'server', 'description' => 'Established Bukkit-compatible server platform'],
        'Bukkit' => ['pattern' => '/\\b(?:craft)?bukkit\\b/i', 'kind' => 'server', 'description' => 'Classic Bukkit-compatible server platform'],
        'Fabric' => ['pattern' => '/\\bfabric\\b/i', 'kind' => 'modded', 'description' => 'Lightweight mod loader and server platform'],
        'Forge' => ['pattern' => '/\\b(?:neo)?forge\\b/i', 'kind' => 'modded', 'description' => 'Modded Minecraft server platform'],
        'Velocity' => ['pattern' => '/\\bvelocity\\b/i', 'kind' => 'proxy', 'description' => 'Modern high-performance Minecraft proxy'],
        'BungeeCord' => ['pattern' => '/\\bbungee(?:cord)?\\b/i', 'kind' => 'proxy', 'description' => 'Traditional Minecraft proxy platform'],
        'Waterfall' => ['pattern' => '/\\bwaterfall\\b/i', 'kind' => 'proxy', 'description' => 'BungeeCord-compatible proxy'],
    ];

    public function __construct(
        private ConnectionInterface $connection,
        private VariableValidatorService $variables,
        private ReinstallServerService $reinstall,
        private DaemonFileRepository $files,
        private DaemonServerRepository $servers,
    ) {
    }

    /** @return array<string, mixed> */
    public function options(Server $server): array
    {
        $eggs = Egg::query()->with('variables')->get()
            ->map(fn (Egg $egg) => $this->eggOption($egg))
            ->filter()
            ->groupBy('platform');

        $platforms = collect(self::PLATFORMS)
            ->map(function (array $definition, string $platform) use ($eggs) {
                $candidates = $eggs->get($platform, collect())->values();
                if ($candidates->isEmpty()) {
                    return null;
                }

                return [
                    'name' => $platform,
                    'initial' => substr($platform, 0, 1),
                    'kind' => $definition['kind'],
                    'description' => $definition['description'],
                    'versions_count' => $candidates->sum(fn (array $candidate) => max(1, count($candidate['versions']))),
                    'candidates' => $candidates->all(),
                ];
            })
            ->filter()
            ->values()
            ->all();

        return [
            'current' => $this->currentInstallation($server),
            'platforms' => $platforms,
        ];
    }

    /** @param array{egg_id:int,version?:string|null,build?:string|null,wipe:bool} $data */
    public function change(Server $server, array $data): Server
    {
        if (!$server->canBeReinstalled()) {
            throw new DisplayException('This server is configured to skip install scripts and cannot be reinstalled. Ask an administrator to enable its installation script first.');
        }

        /** @var Egg $egg */
        $egg = Egg::query()->with('variables')->findOrFail($data['egg_id']);
        if (!$this->eggOption($egg)) {
            throw new DisplayException('That server software is not available through Version Changer. Import and configure a supported egg first.');
        }

        if ($data['wipe']) {
            $this->wipeFiles($server);
        }

        $server = $this->connection->transaction(function () use ($server, $egg, $data) {
            $environment = $this->environmentFor($server, $egg, $data);
            $validated = $this->variables
                ->setUserLevel(User::USER_LEVEL_ADMIN)
                ->handle($egg->id, $environment);

            $image = Arr::first(array_values($egg->docker_images ?? []));
            if (!$image) {
                throw new DisplayException('The selected egg has no Docker image configured.');
            }

            $server->forceFill([
                'egg_id' => $egg->id,
                'nest_id' => $egg->nest_id,
                'startup' => $egg->startup,
                'image' => $image,
                'skip_scripts' => false,
            ])->saveOrFail();

            $variableIds = $validated->pluck('id')->all();
            ServerVariable::query()->where('server_id', $server->id)->whereNotIn('variable_id', $variableIds)->delete();
            foreach ($validated as $variable) {
                ServerVariable::query()->updateOrCreate(
                    ['server_id' => $server->id, 'variable_id' => $variable->id],
                    ['variable_value' => $variable->value ?? '']
                );
            }

            return $server->fresh();
        });

        // Sync first so a running Wings instance receives the new egg configuration before
        // the install endpoint is called. Wings also fetches current configuration on boot.
        try {
            $this->servers->setServer($server)->sync();
        } catch (DaemonConnectionException $exception) {
            Log::warning('Version Changer could not sync Wings before reinstall.', ['server_id' => $server->id, 'exception' => $exception]);
        }

        return $this->reinstall->handle($server);
    }

    /** @return array<string, mixed>|null */
    private function eggOption(Egg $egg): ?array
    {
        $platform = $this->platformFor($egg);
        if (!$platform) {
            return null;
        }

        $version = $this->versionVariable($egg->variables);
        $build = $this->buildVariable($egg->variables);
        $versions = $version ? $this->valuesFor($version) : [];
        $customVersionAllowed = $version ? !str_contains($version->rules, 'in:') : false;

        // Eggs whose version variable accepts arbitrary releases (for example a
        // Paper egg with VERSION=latest) otherwise expose only "latest". Fetch
        // the official release catalogue so customers can choose every actual
        // version the egg can install, while keeping the egg validation and
        // install script as the final authority.
        if ($version && $customVersionAllowed) {
            $versions = array_values(array_unique(array_merge($versions, $this->catalogVersions($platform))));
        }

        return [
            'egg_id' => $egg->id,
            'egg_name' => $egg->name,
            'platform' => $platform,
            'versions' => $versions,
            'default_version' => $version?->default_value,
            'version_variable' => $version?->env_variable,
            'builds' => $build ? $this->valuesFor($build) : [],
            'default_build' => $build?->default_value,
            'build_variable' => $build?->env_variable,
            'custom_version_allowed' => $customVersionAllowed,
            'custom_build_allowed' => $build ? !str_contains($build->rules, 'in:') : false,
        ];
    }

    /** @return array<string, string> */
    private function environmentFor(Server $server, Egg $egg, array $data): array
    {
        $previous = $server->variables()->get()->keyBy('env_variable');
        $environment = [];
        foreach ($egg->variables as $variable) {
            $environment[$variable->env_variable] = $previous->get($variable->env_variable)?->server_value ?? $variable->default_value;
        }

        if (($version = $this->versionVariable($egg->variables)) && array_key_exists('version', $data) && $data['version'] !== null) {
            $environment[$version->env_variable] = (string) $data['version'];
        }
        if (($build = $this->buildVariable($egg->variables)) && array_key_exists('build', $data) && $data['build'] !== null) {
            $environment[$build->env_variable] = (string) $data['build'];
        }

        return $environment;
    }

    private function currentInstallation(Server $server): array
    {
        $server->loadMissing('egg.variables');
        $option = $this->eggOption($server->egg);
        $variables = $server->variables()->get()->keyBy('env_variable');

        return [
            'platform' => $option['platform'] ?? $server->egg->name,
            'egg_name' => $server->egg->name,
            'version' => $option && $option['version_variable'] ? ($variables->get($option['version_variable'])?->server_value ?: $option['default_version']) : null,
            'build' => $option && $option['build_variable'] ? ($variables->get($option['build_variable'])?->server_value ?: $option['default_build']) : null,
        ];
    }

    private function platformFor(Egg $egg): ?string
    {
        foreach (self::PLATFORMS as $name => $definition) {
            if (preg_match($definition['pattern'], $egg->name)) {
                return $name;
            }
        }

        return null;
    }

    /** @param Collection<int, EggVariable> $variables */
    private function versionVariable(Collection $variables): ?EggVariable
    {
        $explicit = $variables->first(fn (EggVariable $variable) => (bool) preg_match('/(?:MINECRAFT|MC|SERVER)_?VERSION|^VERSION$/i', $variable->env_variable));
        if ($explicit) {
            return $explicit;
        }

        // Official eggs do not all use the same name: Vanilla and BungeeCord
        // use VANILLA_VERSION and BUNGEE_VERSION respectively. Prefer the
        // explicit Minecraft fields above, then accept the platform version
        // field while leaving a Forge build override out of the selector.
        return $variables->first(fn (EggVariable $variable) => (bool) preg_match('/_VERSION$/i', $variable->env_variable)
            && !in_array(strtoupper($variable->env_variable), ['FORGE_VERSION', 'BUILD_VERSION'], true));
    }

    /** @param Collection<int, EggVariable> $variables */
    private function buildVariable(Collection $variables): ?EggVariable
    {
        return $variables->first(fn (EggVariable $variable) => (bool) preg_match('/(?:^|_)(?:BUILD|BUILD_NUMBER|PAPER_BUILD|SERVER_BUILD)(?:$|_)/i', $variable->env_variable));
    }

    /** @return list<string> */
    private function valuesFor(EggVariable $variable): array
    {
        $values = [$variable->default_value];
        if (preg_match('/(?:^|\\|)in:([^|]+)/', $variable->rules, $matches)) {
            $values = array_merge($values, explode(',', $matches[1]));
        }

        return array_values(array_unique(array_filter(array_map('trim', $values), fn (string $value) => $value !== '')));
    }

    /**
     * Return only official, stable Minecraft release identifiers. A network
     * failure is intentionally non-fatal: the configured egg values remain
     * available and no version is invented by the Panel.
     *
     * @return list<string>
     */
    private function catalogVersions(string $platform): array
    {
        return match ($platform) {
            'Paper', 'Folia', 'Velocity', 'Waterfall' => $this->paperMcVersions(strtolower($platform)),
            'Purpur' => $this->purpurVersions(),
            'Fabric' => $this->fabricVersions(),
            'Vanilla' => $this->vanillaVersions(),
            'Forge' => $this->forgeVersions(),
            'BungeeCord' => $this->bungeeBuilds(),
            default => [],
        };
    }

    /** @return list<string> */
    private function paperMcVersions(string $project): array
    {
        return Cache::remember("version-changer:papermc:v2:{$project}", now()->addHours(6), function () use ($project): array {
            try {
                // Fill is PaperMC's current public catalogue. The old v2 endpoint
                // no longer powers current projects, which left every egg with its
                // single fallback/default version.
                $response = Http::acceptJson()->timeout(8)->get("https://fill.papermc.io/v3/projects/{$project}");
                if (!$response->successful()) {
                    return [];
                }

                return $this->releaseVersions(Arr::flatten($response->json('versions', [])));
            } catch (\Throwable $exception) {
                Log::notice('Could not retrieve the PaperMC version catalogue.', ['project' => $project, 'exception' => $exception->getMessage()]);

                return [];
            }
        });
    }

    /** @return list<string> */
    private function vanillaVersions(): array
    {
        return Cache::remember('version-changer:vanilla', now()->addHours(6), function (): array {
            try {
                $response = Http::acceptJson()->timeout(8)->get('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json');
                if (!$response->successful()) {
                    return [];
                }

                return $this->releaseVersions(collect($response->json('versions', []))
                    ->where('type', 'release')
                    ->pluck('id')
                    ->filter(fn ($version) => is_string($version) && preg_match('/^\d+\.\d+(?:\.\d+)?$/', $version))
                    ->values()
                    ->all());
            } catch (\Throwable $exception) {
                Log::notice('Could not retrieve the Minecraft version catalogue.', ['exception' => $exception->getMessage()]);

                return [];
            }
        });
    }

    /** @return list<string> */
    private function purpurVersions(): array
    {
        return Cache::remember('version-changer:purpur', now()->addHours(6), function (): array {
            try {
                $response = Http::acceptJson()->timeout(8)->get('https://api.purpurmc.org/v2/purpur');
                if (!$response->successful()) {
                    return [];
                }

                return $this->releaseVersions($response->json('versions', []));
            } catch (\Throwable $exception) {
                Log::notice('Could not retrieve the Purpur version catalogue.', ['exception' => $exception->getMessage()]);

                return [];
            }
        });
    }

    /** @return list<string> */
    private function fabricVersions(): array
    {
        return Cache::remember('version-changer:fabric', now()->addHours(6), function (): array {
            try {
                $response = Http::acceptJson()->timeout(8)->get('https://meta.fabricmc.net/v2/versions/game');
                if (!$response->successful()) {
                    return [];
                }

                return $this->releaseVersions(collect($response->json())
                    ->filter(fn ($version) => is_array($version) && ($version['stable'] ?? false) && isset($version['version']))
                    ->pluck('version')
                    ->filter(fn ($version) => is_string($version) && preg_match('/^\d+\.\d+(?:\.\d+)?$/', $version))
                    ->values()
                    ->all());
            } catch (\Throwable $exception) {
                Log::notice('Could not retrieve the Fabric version catalogue.', ['exception' => $exception->getMessage()]);

                return [];
            }
        });
    }

    /** @return list<string> */
    private function forgeVersions(): array
    {
        return Cache::remember('version-changer:forge', now()->addHours(6), function (): array {
            try {
                $response = Http::acceptJson()->timeout(8)->get('https://files.minecraftforge.net/maven/net/minecraftforge/forge/promotions_slim.json');
                if (!$response->successful()) {
                    return [];
                }

                return $this->releaseVersions(array_map(fn (string $key) => explode('-', $key, 2)[0], array_keys($response->json('promos', []))));
            } catch (\Throwable $exception) {
                Log::notice('Could not retrieve the Forge version catalogue.', ['exception' => $exception->getMessage()]);

                return [];
            }
        });
    }

    /** @return list<string> */
    private function bungeeBuilds(): array
    {
        return Cache::remember('version-changer:bungeecord', now()->addHours(6), function (): array {
            try {
                $response = Http::acceptJson()->timeout(8)->get('https://ci.md-5.net/job/BungeeCord/api/json?tree=builds[number]');
                if (!$response->successful()) {
                    return [];
                }

                return collect($response->json('builds', []))
                    ->pluck('number')
                    ->filter(fn ($build) => is_int($build) || ctype_digit((string) $build))
                    ->map(fn ($build) => (string) $build)
                    ->take(10)
                    ->values()
                    ->all();
            } catch (\Throwable $exception) {
                Log::notice('Could not retrieve the BungeeCord build catalogue.', ['exception' => $exception->getMessage()]);

                return [];
            }
        });
    }

    /** @param array<int, mixed> $versions @return list<string> */
    private function releaseVersions(array $versions): array
    {
        $releases = array_values(array_unique(array_filter($versions, fn ($version) => is_string($version) && preg_match('/^\d+\.\d+(?:\.\d+)?$/', $version))));
        usort($releases, fn (string $left, string $right) => version_compare($right, $left));

        return array_slice($releases, 0, 10);
    }

    private function wipeFiles(Server $server): void
    {
        try {
            $files = $this->files->setServer($server)->getDirectory('/');
            $names = collect($files)->pluck('name')->filter(fn ($name) => is_string($name) && !in_array($name, ['.', '..'], true))->values()->all();
            if ($names) {
                $this->files->setServer($server)->deleteFiles('/', $names);
            }
        } catch (DaemonConnectionException $exception) {
            throw new DisplayException('The Panel could not wipe the server files because Wings is unavailable. No version change was started.');
        }
    }
}
