<?php

namespace Pterodactyl\Services\Subdomains;

interface DNSProvider
{
    /** @return array{id:string} */
    public function createRecord(string $zoneId, array $record): array;
    /** @return array{id:string} */
    public function updateRecord(string $zoneId, string $recordId, array $record): array;
    public function deleteRecord(string $zoneId, string $recordId): void;
    /** @return array<string, mixed>|null */
    public function findRecord(string $zoneId, string $type, string $name): ?array;
    public function testConnection(): void;
}
