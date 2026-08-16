<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::table('server_optimizer_runs', function (Blueprint $table) {
            $table->boolean('automatic')->default(false)->after('status');
            $table->json('trigger')->nullable()->after('summary');
            $table->timestamp('flagged_at')->nullable()->after('completed_at');
            $table->timestamp('read_at')->nullable()->after('flagged_at');
            $table->index(['server_id', 'automatic', 'flagged_at', 'read_at'], 'optimizer_reports_unread_index');
        });
    }

    public function down(): void
    {
        Schema::table('server_optimizer_runs', function (Blueprint $table) {
            $table->dropIndex('optimizer_reports_unread_index');
            $table->dropColumn(['automatic', 'trigger', 'flagged_at', 'read_at']);
        });
    }
};
