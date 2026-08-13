<?php

namespace Pterodactyl\Console\Commands;

use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use PDO;
use RuntimeException;

class MigrateLegacySqliteCommand extends Command
{
    protected $signature = 'panel:migrate-legacy-sqlite
        {--path=/legacy/database.sqlite : Read-only path to the legacy SQLite database}
        {--force : Required acknowledgement that the destination MariaDB database is fresh}';

    protected $description = 'Copy FluidPanel records from a legacy SQLite database into a fresh MariaDB database.';

    public function handle(): int
    {
        if (!$this->option('force')) {
            $this->error('Refusing to run without --force. This command is only for a fresh MariaDB database.');

            return self::FAILURE;
        }

        if (!in_array(config('database.default'), ['mysql', 'mariadb'], true)) {
            $this->error('Set DB_CONNECTION to mysql or mariadb before running this command.');

            return self::FAILURE;
        }

        $path = (string) $this->option('path');
        if (!is_file($path) || !is_readable($path)) {
            $this->error("Legacy SQLite database is not readable: {$path}");

            return self::FAILURE;
        }

        $legacy = new PDO('sqlite:' . $path, null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
        $connection = DB::connection();
        $tables = $legacy->query("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            ->fetchAll(PDO::FETCH_COLUMN);

        $connection->statement('SET FOREIGN_KEY_CHECKS=0');
        try {
            foreach ($tables as $table) {
                if ($table === 'migrations' || !Schema::hasTable($table)) {
                    continue;
                }

                $columns = array_column($legacy->query("PRAGMA table_info(\"{$table}\")")->fetchAll(PDO::FETCH_ASSOC), 'name');
                $targetColumns = Schema::getColumnListing($table);
                $columns = array_values(array_intersect($columns, $targetColumns));
                if ($columns === []) {
                    continue;
                }

                // The MariaDB schema was just created by Laravel migrations.
                // Delete any seed/runtime rows, but keep its migration history.
                $connection->table($table)->delete();

                $query = $legacy->query("SELECT " . implode(', ', array_map(fn ($column) => "\"{$column}\"", $columns)) . " FROM \"{$table}\"");
                $rows = [];
                $count = 0;
                while (($row = $query->fetch(PDO::FETCH_ASSOC)) !== false) {
                    $rows[] = $row;
                    if (count($rows) === 250) {
                        $connection->table($table)->insert($rows);
                        $count += count($rows);
                        $rows = [];
                    }
                }
                if ($rows !== []) {
                    $connection->table($table)->insert($rows);
                    $count += count($rows);
                }

                $this->line("Copied {$count} row(s) from {$table}.");
            }
        } catch (\Throwable $exception) {
            throw new RuntimeException('SQLite-to-MariaDB migration failed. The legacy SQLite file remains unchanged.', 0, $exception);
        } finally {
            $connection->statement('SET FOREIGN_KEY_CHECKS=1');
        }

        $this->info('Legacy SQLite data copy complete. Verify panel users, nodes and servers before retiring SQLite.');

        return self::SUCCESS;
    }
}
