<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::table('nodes', function (Blueprint $table) {
            $table->unsignedBigInteger('uptime_seconds')->nullable()->after('memory_type');
            $table->timestamp('uptime_reported_at')->nullable()->after('uptime_seconds')->index();
        });
    }

    public function down(): void
    {
        Schema::table('nodes', function (Blueprint $table) {
            $table->dropColumn(['uptime_seconds', 'uptime_reported_at']);
        });
    }
};
