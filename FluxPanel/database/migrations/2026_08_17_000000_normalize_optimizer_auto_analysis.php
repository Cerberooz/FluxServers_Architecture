<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        if (!Schema::hasColumn('servers', 'optimizer_auto_analysis')) return;

        DB::table('servers')->whereNull('optimizer_auto_analysis')->update(['optimizer_auto_analysis' => true]);
    }

    public function down(): void
    {
        // Existing server preferences are intentionally retained.
    }
};
