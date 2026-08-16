<?php

namespace Pterodactyl\Services\Minecraft;

/**
 * Performs the standard Minecraft status ping against an allocation. Wings
 * exposes container resources, but not the number of connected players.
 */
class MinecraftStatusService
{
    /** @return array{online:int,max:int}|null */
    public function players(string $ip, int $port): ?array
    {
        if (!filter_var($ip, FILTER_VALIDATE_IP) || $port < 1 || $port > 65535) return null;

        $host = filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6) ? "[{$ip}]" : $ip;
        $socket = @stream_socket_client("tcp://{$host}:{$port}", $errno, $error, 0.8, STREAM_CLIENT_CONNECT);
        if (!is_resource($socket)) return null;

        try {
            stream_set_timeout($socket, 1);
            // Modern servers normally answer status requests despite a protocol version mismatch.
            $handshake = $this->varInt(0) . $this->varInt(767) . $this->string($ip) . pack('n', $port) . $this->varInt(1);
            fwrite($socket, $this->varInt(strlen($handshake)) . $handshake);
            fwrite($socket, "\x01\x00");
            $this->readVarInt($socket);
            $this->readVarInt($socket);
            $length = $this->readVarInt($socket);
            if ($length < 1 || $length > 1_048_576) return null;
            $response = json_decode($this->read($socket, $length), true);
            if (!is_array($response) || !isset($response['players']['online'])) return null;

            return ['online' => max(0, (int) $response['players']['online']), 'max' => max(0, (int) ($response['players']['max'] ?? 0))];
        } catch (\Throwable) {
            return null;
        } finally {
            fclose($socket);
        }
    }

    private function string(string $value): string { return $this->varInt(strlen($value)) . $value; }

    private function varInt(int $value): string
    {
        $output = '';
        do {
            $byte = $value & 0x7F;
            $value >>= 7;
            if ($value !== 0) $byte |= 0x80;
            $output .= chr($byte);
        } while ($value !== 0);
        return $output;
    }

    private function readVarInt($socket): int
    {
        $value = 0;
        for ($position = 0; $position < 5; ++$position) {
            $byte = fread($socket, 1);
            if ($byte === false || $byte === '') throw new \RuntimeException('Unexpected end of Minecraft status response.');
            $value |= (ord($byte) & 0x7F) << (7 * $position);
            if ((ord($byte) & 0x80) === 0) return $value;
        }
        throw new \RuntimeException('Invalid Minecraft status response.');
    }

    private function read($socket, int $length): string
    {
        $output = '';
        while (strlen($output) < $length) {
            $chunk = fread($socket, $length - strlen($output));
            if ($chunk === false || $chunk === '') throw new \RuntimeException('Unexpected end of Minecraft status response.');
            $output .= $chunk;
        }
        return $output;
    }
}
