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
        $platform = Str::contains($name, 'folia') ? 'folia' : (Str::contains($name, 'purpur') ? 'purpur' : (Str::contains($name, 'paper') ? 'paper' : (Str::contains($name, 'spigot') ? 'spigot' : (Str::contains($name, 'bukkit') ? 'bukkit' : null))));
        $version = null;
        foreach ($server->variables as $variable) if (preg_match('/minecraft.*version/i', $variable->name ?? '') && preg_match('/(\d+\.\d+(?:\.\d+)?)/', $variable->server_value ?? '', $match)) $version = $match[1];
        if (!$version && preg_match('/(\d+\.\d+(?:\.\d+)?)/', $server->egg->name, $match)) $version = $match[1];
        return ['supported' => (bool) $platform, 'platform' => $platform, 'loaders' => match ($platform) { 'paper' => ['paper', 'spigot', 'bukkit'], 'purpur' => ['purpur', 'paper', 'spigot', 'bukkit'], 'folia' => ['folia', 'paper'], 'spigot' => ['spigot', 'bukkit'], 'bukkit' => ['bukkit'], default => [] }, 'version' => $version, 'directory' => self::DIRECTORY];
    }

    public function search(Server $server, string $query): array
    {
        $context = $this->context($server);
        if (!$context['supported'] || !$context['version']) return ['context' => $context, 'projects' => []];
        $facets = json_encode([['project_type:plugin'], ['server_side:required'], ["versions:{$context['version']}"]]);
        $data = $this->api('search', ['query' => $query, 'facets' => $facets, 'limit' => 20]);
        $projects = collect($data['hits'] ?? [])->map(function (array $project) use ($context) {
            $version = $this->resolveCompatibleVersion($project['project_id'], $context);
            return ['id' => $project['project_id'], 'name' => $project['title'], 'author' => $project['author'], 'description' => $project['description'], 'icon' => $project['icon_url'] ?? null, 'downloads' => $project['downloads'] ?? 0, 'versions' => $project['versions'] ?? [], 'platforms' => $project['categories'] ?? [], 'compatible' => (bool) $version, 'reason' => $version ? null : 'No compatible release exists for this Minecraft version and server platform.', 'version' => $version];
        })->values()->all();
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
            $hash = null; $known = null;
            try { $hash = hash('sha512', $this->files->setServer($server)->getContent(self::DIRECTORY . '/' . $filename, 104857600)); $known = $this->api('version_file/' . $hash, ['algorithm' => 'sha512']); } catch (\Throwable) { }
            $project = $known['project_id'] ?? $managed->get($filename)?->project_id;
            $latest = $project && $context['version'] ? $this->resolveCompatibleVersion($project, $context) : null;
            $items[] = ['filename' => $filename, 'disabled' => $disabled, 'sha512' => $hash, 'project_id' => $project, 'version_id' => $known['id'] ?? $managed->get($filename)?->version_id, 'name' => $known['name'] ?? preg_replace('/\.jar(?:\.disabled)?$/i', '', $filename), 'status' => $disabled ? 'disabled' : ($project ? 'recognized' : 'external'), 'latest' => $latest, 'update_available' => $latest && ($known['id'] ?? null) !== $latest['id']];
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
