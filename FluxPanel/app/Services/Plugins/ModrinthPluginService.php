<?php
namespace Pterodactyl\Services\Plugins;

use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Str;
use Pterodactyl\Exceptions\DisplayException;
use Pterodactyl\Models\Server;
use Pterodactyl\Models\ServerManagedPlugin;
use Pterodactyl\Repositories\Wings\DaemonFileRepository;

class ModrinthPluginService
{
    private const DIRECTORY = '/plugins';
    public function __construct(private DaemonFileRepository $files) {}

    public function context(Server $server): array
    {
        $name = Str::lower($server->egg->name . ' ' . $server->nest->name);
        $runtime = $this->runtimeMetadata($server);
        // A verified runtime signature always wins over the egg name. Eggs can be
        // reused, renamed, or changed after a server has been provisioned.
        $platform = $runtime['software']
            ? $this->pluginPlatformForSoftware($runtime['software'])
            : (Str::contains($name, 'folia') ? 'folia' : (Str::contains($name, 'purpur') ? 'purpur' : (Str::contains($name, 'leaf') ? 'leaf' : (Str::contains($name, 'paper') ? 'paper' : (Str::contains($name, 'spigot') ? 'spigot' : (Str::contains($name, 'bukkit') ? 'bukkit' : null))))));
        $version = $this->minecraftVersion($server);
        return ['supported' => (bool) $platform, 'platform' => $platform, 'loaders' => match ($platform) { 'paper', 'leaf' => ['paper', 'spigot', 'bukkit'], 'purpur' => ['purpur', 'paper', 'spigot', 'bukkit'], 'folia' => ['folia', 'paper'], 'spigot' => ['spigot', 'bukkit'], 'bukkit' => ['bukkit'], default => [] }, 'version' => $version, 'directory' => self::DIRECTORY];
    }

    /**
     * Read the running server's own log for the actual Minecraft release. This
     * deliberately does not derive a version from an egg name: eggs can be
     * configured as "latest" and can drift from the version actually running.
     */
    public function runtimeMetadata(Server $server): array
    {
        // Bump this key whenever parsing rules change so a previous, incorrect
        // classification cannot remain visible for the old cache lifetime.
        $cacheKey = "server-runtime-metadata:v2:{$server->id}";
        $cached = Cache::get($cacheKey);
        if (is_array($cached) && !empty($cached['minecraft_version'])) {
            return $cached;
        }

        $log = '';
        // Wings accepts relative paths. Some older Wings setups reject a leading
        // slash, while some installations kept the historic leading slash.
        foreach (['logs/latest.log', '/logs/latest.log'] as $path) {
            try {
                $log = $this->files->setServer($server)->getContent($path, 524288);
                if ($log !== '') {
                    break;
                }
            } catch (\Throwable) {
                // A server that has never started has no runtime log yet.
            }
        }

        $metadata = [
            'minecraft_version' => $this->runtimeMinecraftVersion($log),
            'software' => $this->runtimeSoftware($log),
        ];

        // Do not cache a failed read: a starting server writes this information
        // moments later and the next request should immediately see it.
        if ($metadata['minecraft_version']) {
            Cache::put($cacheKey, $metadata, now()->addMinutes(5));
        }

        return $metadata;
    }

    public function search(Server $server, string $query): array
    {
        $context = $this->context($server);
        if (!$context['supported'] || !$context['version']) return ['context' => $context, 'projects' => []];
        // The search index can filter plugins by their Bukkit-family loader. This
        // keeps Fabric/Forge/NeoForge mods out of the Plugin Manager entirely.
        // Loader facets in the same group are ORed by Modrinth, so a Paper server
        // can still find Bukkit and Spigot plugins where appropriate.
        $facets = json_encode([
            ['project_type:plugin'],
            ['server_side:required'],
            ["versions:{$context['version']}"],
            array_map(fn (string $loader) => "categories:{$loader}", $context['loaders']),
        ]);
        $data = $this->api('search', ['query' => trim($query), 'facets' => $facets, 'limit' => 12]);

        // Do not resolve a release for every hit here. That used to add one
        // sequential HTTP request per result and made typing a search feel slow.
        // Install/download still resolve the exact release server-side, so this
        // remains safe if Modrinth's search index is briefly stale.
        $projects = collect($data['hits'] ?? [])
            ->filter(fn (array $project) => ($project['project_type'] ?? null) === 'plugin')
            ->filter(function (array $project) use ($context) {
                $categories = array_map('strtolower', $project['categories'] ?? []);

                return !empty(array_intersect($context['loaders'], $categories));
            })
            ->map(fn (array $project) => [
                'id' => $project['project_id'],
                'name' => $project['title'],
                'author' => $project['author'],
                'description' => $project['description'],
                'icon' => $project['icon_url'] ?? null,
                'downloads' => $project['downloads'] ?? 0,
                'versions' => $project['versions'] ?? [],
                'platforms' => $project['categories'] ?? [],
                'compatible' => true,
                'reason' => null,
                'version' => null,
            ])
            ->values()
            ->all();
        return compact('context', 'projects');
    }

    public function installed(Server $server): array
    {
        $context = $this->context($server);
        $this->ensureDirectory($server);
        $managed = $server->managedPlugins()->get()->keyBy('filename');
        $items = [];
        foreach ($this->files->setServer($server)->getDirectory(self::DIRECTORY) as $entry) {
            $filename = $entry['name'] ?? '';
            if (!preg_match('/\.jar(?:\.disabled)?$/i', $filename) || str_contains($filename, '/') || str_contains($filename, '\\')) continue;
            $disabled = Str::endsWith(Str::lower($filename), '.disabled');
            $known = $managed->get($filename);

            // Do not download and hash every JAR, then make two Modrinth API calls
            // per file, just to render the Installed tab. The panel records
            // Modrinth-managed plugins when it installs them; other JARs remain
            // visible as external plugins without delaying the entire page.
            $items[] = [
                'filename' => $filename,
                'disabled' => $disabled,
                'sha512' => $known?->sha512,
                'project_id' => $known?->project_id,
                'version_id' => $known?->version_id,
                'name' => preg_replace('/\.jar(?:\.disabled)?$/i', '', $filename),
                'status' => $disabled ? 'disabled' : ($known?->project_id ? 'managed' : 'external'),
                'latest' => null,
                'update_available' => false,
            ];
        }
        return ['context' => $context, 'plugins' => $items];
    }

    public function install(Server $server, string $projectId, array $includeDependencies = []): array
    {
        $context = $this->context($server);
        if (!$context['supported'] || !$context['version']) throw new DisplayException('This server software or Minecraft version does not support managed plugins.');
        $version = $this->resolveCompatibleVersion($this->projectId($projectId), $context);
        if (!$version) throw new DisplayException('No compatible Modrinth release is available for this server.');
        $dependencies = $this->dependencies($version, $context);
        $required = collect($dependencies)->where('type', 'required')->map(fn ($dependency) => $this->dependencyKey($dependency))->filter()->all();
        if (array_diff($required, $includeDependencies)) throw new DisplayException('Confirm all required dependencies before installing.');
        $existing = $this->installed($server)['plugins'];
        foreach ($dependencies as $dependency) {
            $dependencyProject = $dependency['project_id'] ?? null;
            if ($dependency['type'] === 'incompatible' && $this->hasProject($server, $dependencyProject, $existing)) throw new DisplayException('An installed plugin is incompatible with this project.');
            if ($dependency['type'] === 'required' && $dependencyProject && collect($existing)->contains(fn ($plugin) => $plugin['project_id'] === $dependencyProject && $plugin['disabled'])) throw new DisplayException('A required dependency is disabled. Enable it before installing this plugin.');
        }
        $installed = [];
        foreach ([...$this->resolveRequired($dependencies, $context, $includeDependencies), $version] as $release) $installed[] = $this->downloadAndInstall($server, $release);
        return $installed;
    }

    public function toggle(Server $server, string $filename, bool $enable): void
    {
        $filename = $this->filename($filename);
        if ($enable && !Str::endsWith(Str::lower($filename), '.disabled')) throw new DisplayException('This plugin is already enabled.');
        if (!$enable && Str::endsWith(Str::lower($filename), '.disabled')) throw new DisplayException('This plugin is already disabled.');
        $from = $filename;
        $to = $enable ? substr($filename, 0, -9) : $filename . '.disabled';
        $existing = collect($this->files->setServer($server)->getDirectory(self::DIRECTORY))->pluck('name')->all();
        if (in_array($to, $existing, true)) throw new DisplayException('A plugin with that enabled/disabled filename already exists.');
        if (!in_array($from, $existing, true)) throw new DisplayException('That plugin file no longer exists.');
        $this->files->setServer($server)->renameFiles(self::DIRECTORY, [['from' => $from, 'to' => $to]]);
        ServerManagedPlugin::query()->where('server_id', $server->id)->where('filename', $from)->update(['filename' => $to, 'disabled' => !$enable]);
    }

    public function update(Server $server, string $filename, string $projectId, array $includeDependencies = []): array
    {
        $filename = $this->filename($filename);
        $context = $this->context($server);
        $version = $this->resolveCompatibleVersion($this->projectId($projectId), $context);
        if (!$version) throw new DisplayException('No compatible update is available for this server.');
        $dependencies = $this->dependencies($version, $context);
        $required = collect($dependencies)->where('type', 'required')->map(fn ($dependency) => $this->dependencyKey($dependency))->filter()->all();
        if (array_diff($required, $includeDependencies)) throw new DisplayException('Confirm all required dependencies before updating.');
        foreach ($this->resolveRequired($dependencies, $context, $includeDependencies) as $dependency) $this->downloadAndInstall($server, $dependency);
        $disabled = Str::endsWith(Str::lower($filename), '.disabled');
        $installed = $this->downloadAndInstall($server, $version, $disabled);
        $newFilename = $installed['filename'];
        if ($newFilename !== $filename) {
            $this->files->setServer($server)->deleteFiles(self::DIRECTORY, [$filename]);
            $server->managedPlugins()->where('filename', $filename)->delete();
        }
        return $installed;
    }

    public function remove(Server $server, string $filename): void { $filename = $this->filename($filename); $this->files->setServer($server)->deleteFiles(self::DIRECTORY, [$filename]); $server->managedPlugins()->where('filename', $filename)->delete(); }
    public function downloadUrl(Server $server, string $projectId): string { $release = $this->resolveCompatibleVersion($this->projectId($projectId), $this->context($server), false) ?? throw new DisplayException('No downloadable release was found.'); return $this->primaryFile($release)['url']; }
    public function dependenciesFor(Server $server, string $projectId): array { $release = $this->resolveCompatibleVersion($this->projectId($projectId), $this->context($server)) ?? throw new DisplayException('No compatible release is available.'); return $this->dependencies($release, $this->context($server)); }

    private function resolveCompatibleVersion(string $projectId, array $context, bool $compatible = true): ?array { $query = $compatible ? ['loaders' => json_encode($context['loaders']), 'game_versions' => json_encode([$context['version']]), 'featured' => 'true', 'include_changelog' => 'false'] : ['include_changelog' => 'false']; $versions = $this->api("project/{$projectId}/version", $query); return collect($versions)->first(fn ($version) => !empty($version['files'])); }
    private function minecraftVersion(Server $server): ?string
    {
        $runtime = $this->runtimeMetadata($server);
        if ($runtime['minecraft_version']) return $runtime['minecraft_version'];

        // EggVariable is joined directly onto Server::variables. Check its
        // human label *and* environment key because community eggs use names
        // such as VERSION, MC_VERSION, or MINECRAFT_VERSION interchangeably.
        foreach ($server->variables as $variable) {
            $label = implode(' ', [$variable->name ?? '', $variable->env_variable ?? '', $variable->description ?? '']);
            $value = $variable->server_value ?? $variable->default_value ?? '';
            if (preg_match('/(?:minecraft|mc)[\s_-]*version|^version$/i', $label)
                && preg_match('/(\d+\.\d+(?:\.\d+)?)/', $value, $match)) return $match[1];
        }

        return null;
    }

    private function runtimeMinecraftVersion(string $log): ?string
    {
        $patterns = [
            '/\bfor\s+Minecraft\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)/i',
            '/\bMinecraft(?:\s+Server)?\s+version\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)/i',
            // Paper and its forks commonly log: "running Paper version
            // 1.21.11-..." rather than "for Minecraft 1.21.11".
            '/\b(?:Leaf|Paper|Purpur|Pufferfish|Folia|Spigot)\s+version\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)/i',
            '/\b(?:Leaf|Paper|Purpur|Pufferfish|Folia|Spigot)\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)(?:[-\s]|$)/i',
        ];

        foreach ($patterns as $pattern) {
            if (preg_match($pattern, $log, $match)) {
                return $match[1];
            }
        }

        return null;
    }

    private function runtimeSoftware(string $log): ?string
    {
        // Only accept a software name when it appears in a recognised startup
        // signature. Looking for a bare word such as "Velocity" is unsafe: it
        // can occur in plugin names, stack traces, or old log entries on a Paper
        // server and used to mislabel Paper installations as Velocity.
        $patterns = [
            '/\bThis\s+server\s+is\s+running\s+(Leaf|Paper|Purpur|Pufferfish|Folia|Spigot|CraftBukkit|Bukkit)\s+version\b/i',
            '/\[(?:bootstrap|servermain)\][^\n]*\b(?:loading|starting)\s+(Leaf|Paper|Purpur|Pufferfish|Folia|Spigot|CraftBukkit|Bukkit)\b/i',
            '/\b(?:loading|running)\s+(Leaf|Paper|Purpur|Pufferfish|Folia|Spigot|CraftBukkit|Bukkit)\s+(?:version|[0-9])/i',
            '/\bThis\s+server\s+is\s+running\s+(Velocity|BungeeCord|Waterfall)\s+version\b/i',
            '/\bStarting\s+(Velocity|BungeeCord|Waterfall)\s+(?:version|build|[0-9])/i',
        ];

        foreach ($patterns as $pattern) {
            if (preg_match($pattern, $log, $match)) {
                return $this->canonicalSoftware($match[1]);
            }
        }

        return null;
    }

    private function pluginPlatformForSoftware(string $software): ?string
    {
        return match (Str::lower($software)) {
            'paper' => 'paper',
            'leaf' => 'leaf',
            'purpur' => 'purpur',
            'pufferfish' => 'purpur',
            'folia' => 'folia',
            'spigot' => 'spigot',
            'craftbukkit', 'bukkit' => 'bukkit',
            default => null,
        };
    }

    private function canonicalSoftware(string $software): string
    {
        return match (Str::lower($software)) {
            'paper' => 'Paper',
            'leaf' => 'Leaf',
            'purpur' => 'Purpur',
            'pufferfish' => 'Pufferfish',
            'folia' => 'Folia',
            'spigot' => 'Spigot',
            'craftbukkit' => 'CraftBukkit',
            'bukkit' => 'Bukkit',
            'velocity' => 'Velocity',
            'bungeecord' => 'BungeeCord',
            'waterfall' => 'Waterfall',
            default => $software,
        };
    }
    private function dependencies(array $version, array $context): array { return collect($version['dependencies'] ?? [])->map(function ($dependency) use ($context) { if (($dependency['dependency_type'] ?? '') === 'required' && empty($dependency['version_id']) && !empty($dependency['project_id'])) $dependency['resolved'] = $this->resolveCompatibleVersion($dependency['project_id'], $context); return ['type' => $dependency['dependency_type'] ?? 'required', 'project_id' => $dependency['project_id'] ?? null, 'version_id' => $dependency['version_id'] ?? null, 'resolved' => $dependency['resolved'] ?? null]; })->all(); }
    private function dependencyKey(array $dependency): ?string { return $dependency['project_id'] ?? $dependency['version_id'] ?? null; }
    private function resolveRequired(array $dependencies, array $context, array $confirmed): array { return collect($dependencies)->filter(fn ($dependency) => $dependency['type'] === 'required' && in_array($this->dependencyKey($dependency), $confirmed, true))->map(function ($dependency) { $release = $dependency['resolved'] ?? ($dependency['version_id'] ? $this->api('version/' . $dependency['version_id']) : null); if (!$release) throw new DisplayException('A required dependency has no compatible Modrinth release.'); return $release; })->all(); }
    private function downloadAndInstall(Server $server, array $version, bool $disabled = false): array { $file = $this->primaryFile($version); $filename = $this->filename($file['filename']) . ($disabled ? '.disabled' : ''); $response = Http::withUserAgent($this->userAgent())->timeout(120)->get($this->cdn($file['url'])); if (!$response->successful() || strlen($response->body()) > 104857600) throw new DisplayException('Modrinth download failed or exceeded the 100MB plugin limit.'); $body = $response->body(); $expected = $file['hashes']['sha512'] ?? $file['hashes']['sha1'] ?? null; $algorithm = isset($file['hashes']['sha512']) ? 'sha512' : 'sha1'; if (!$expected || !hash_equals($expected, hash($algorithm, $body))) throw new DisplayException('Plugin hash verification failed. Nothing was written to the server.'); $this->ensureDirectory($server); $this->files->setServer($server)->putContent(self::DIRECTORY . '/' . $filename, $body); ServerManagedPlugin::query()->updateOrCreate(['server_id' => $server->id, 'filename' => $filename], ['project_id' => $version['project_id'], 'version_id' => $version['id'], 'sha512' => $file['hashes']['sha512'] ?? null, 'disabled' => $disabled]); return ['filename' => $filename, 'project_id' => $version['project_id'], 'version_id' => $version['id']]; }
    private function primaryFile(array $version): array { $file = collect($version['files'] ?? [])->first(fn ($file) => ($file['primary'] ?? false) && preg_match('/\.jar$/i', $file['filename'] ?? '')) ?? collect($version['files'] ?? [])->first(fn ($file) => preg_match('/\.jar$/i', $file['filename'] ?? '')); if (!$file) throw new DisplayException('This Modrinth release has no downloadable JAR file.'); return $file; }
    private function filename(string $filename): string { if (!preg_match('/^[A-Za-z0-9][A-Za-z0-9._-]*\.jar(?:\.disabled)?$/', $filename)) throw new DisplayException('Invalid plugin filename.'); return $filename; }
    private function cdn(string $url): string { $parts = parse_url($url); if (($parts['scheme'] ?? null) !== 'https' || ($parts['host'] ?? null) !== 'cdn.modrinth.com' || !Str::startsWith($parts['path'] ?? '', '/data/')) throw new DisplayException('Unexpected plugin download URL.'); return $url; }
    private function hasProject(Server $server, ?string $project, array $filesystemPlugins = []): bool { return $project && (collect($filesystemPlugins)->contains(fn ($plugin) => $plugin['project_id'] === $project) || $server->managedPlugins()->where('project_id', $project)->exists()); }
    private function projectId(string $projectId): string { if (!preg_match('/^[A-Za-z0-9_-]{3,64}$/', $projectId)) throw new DisplayException('Invalid Modrinth project identifier.'); return $projectId; }
    private function ensureDirectory(Server $server): void { try { $this->files->setServer($server)->getDirectory(self::DIRECTORY); } catch (\Throwable) { $this->files->setServer($server)->createDirectory('plugins', '/'); } }
    private function api(string $path, array $query = []): array
    {
        $key = 'modrinth:' . sha1($path . json_encode($query));
        if (Cache::has($key)) return Cache::get($key);
        $response = Http::withUserAgent($this->userAgent())->acceptJson()->timeout(20)->get('https://api.modrinth.com/v2/' . ltrim($path, '/'), $query);
        if (!$response->successful()) throw new DisplayException($response->status() === 429 ? 'Modrinth is rate limiting requests. Please try again shortly.' : 'Modrinth API request failed.');
        $resetAt = (int) $response->header('X-Ratelimit-Reset', 0);
        $seconds = $resetAt > time() ? min(max($resetAt - time(), 1), 300) : 300;
        Cache::put($key, $response->json(), now()->addSeconds($seconds));
        return $response->json();
    }
    private function userAgent(): string { return 'FluidPanel Plugin Manager/1.0 (' . (config('app.url') ?: 'https://panel.fluxservers.cloud') . ')'; }
}
