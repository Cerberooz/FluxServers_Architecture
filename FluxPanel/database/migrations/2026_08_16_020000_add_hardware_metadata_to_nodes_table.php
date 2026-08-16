<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::table('nodes', function (Blueprint $table) {
            $table->string('cpu_model')->nullable()->after('memory_overallocate');
            $table->string('memory_type')->nullable()->after('cpu_model');
        });
    }

    public function down(): void
    {
        Schema::table('nodes', function (Blueprint $table) {
            $table->dropColumn(['cpu_model', 'memory_type']);
        });
    }
};
