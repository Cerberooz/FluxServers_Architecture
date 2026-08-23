<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::table('backups', function (Blueprint $table) {
            // This is the node that owns a Wings-local archive.
            $table->unsignedInteger('node_id')->nullable()->after('server_id')->index();
        });

        // Backups created before this feature did not record their source node.
        // Treat them as local to the server's current node so they remain usable
        // after this upgrade. New backups always persist their real source node.
        DB::table('backups')
            ->join('servers', 'servers.id', '=', 'backups.server_id')
            ->where('backups.disk', 'wings')
            ->whereNull('backups.node_id')
            ->update(['backups.node_id' => DB::raw('servers.node_id')]);
    }

    public function down(): void
    {
        Schema::table('backups', function (Blueprint $table) {
            $table->dropIndex(['node_id']);
            $table->dropColumn('node_id');
        });
    }
};
