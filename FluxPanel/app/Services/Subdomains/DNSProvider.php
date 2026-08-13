<?php

namespace Pterodactyl\Services\Subdomains;

interface DNSProvider
{
    /** @return array{id:string} */
    public function createRecord(string $zoneId, array $record): array;
    /** @return array{id:string} */
    public function updateRecord(string $zoneId, string $recordId, array $record): array;
    public function deleteRecord(string $zoneId, string $recordId): void;
    public function testConnection(): void;
}
