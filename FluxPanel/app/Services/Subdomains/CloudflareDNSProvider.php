<?php

namespace Pterodactyl\Services\Subdomains;

use Illuminate\Support\Facades\Crypt;
use Illuminate\Support\Facades\Http;
use Pterodactyl\Exceptions\DisplayException;
use Pterodactyl\Contracts\Repository\SettingsRepositoryInterface;

class CloudflareDNSProvider implements DNSProvider
{
    public function __construct(private SettingsRepositoryInterface $settings) {}

    public function createRecord(string $zoneId, array $record): array { return $this->request('post', "/zones/{$zoneId}/dns_records", $record); }
    public function updateRecord(string $zoneId, string $recordId, array $record): array { return $this->request('put', "/zones/{$zoneId}/dns_records/{$recordId}", $record); }
    public function deleteRecord(string $zoneId, string $recordId): void { $this->request('delete', "/zones/{$zoneId}/dns_records/{$recordId}"); }
    public function testConnection(): void { $this->request('get', '/user/tokens/verify'); }

    private function request(string $method, string $path, array $payload = []): array
    {
        $encrypted = $this->settings->get('subdomains:cloudflare:token');
        if (!$encrypted) throw new DisplayException('Cloudflare is not configured.');
        try { $token = Crypt::decryptString($encrypted); } catch (\Throwable) { throw new DisplayException('The Cloudflare token could not be decrypted.'); }
        $response = Http::baseUrl('https://api.cloudflare.com/client/v4')->withToken($token)->acceptJson()->{$method}($path, $payload);
        $data = $response->json();
        if (!$response->successful() || !($data['success'] ?? false)) {
            throw new DisplayException('Cloudflare DNS request failed: ' . ($data['errors'][0]['message'] ?? $response->status()));
        }
        return $data['result'] ?? [];
    }
}
