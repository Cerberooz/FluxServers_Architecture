<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::table('backups', function (Blueprint $table) {
            // This is the node that owns a Wings-local archive. It intentionally
            // remains nullable for legacy backups, which are treated as unsafe.
            $table->unsignedInteger('node_id')->nullable()->after('server_id')->index();
        });
    }

    public function down(): void
    {
        Schema::table('backups', function (Blueprint $table) {
            $table->dropIndex(['node_id']);
            $table->dropColumn('node_id');
        });
    }
};
