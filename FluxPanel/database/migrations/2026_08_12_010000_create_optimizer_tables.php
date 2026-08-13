<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('server_optimizer_runs', function (Blueprint $table) {
            $table->id();
            $table->unsignedInteger('server_id');
            $table->foreign('server_id')->references('id')->on('servers')->cascadeOnDelete();
            $table->string('type', 24);
            $table->string('status', 16)->default('queued');
            $table->json('summary')->nullable();
            $table->text('error')->nullable();
            $table->timestamp('started_at')->nullable();
            $table->timestamp('completed_at')->nullable();
            $table->timestamps();
            $table->index(['server_id', 'type', 'created_at']);
        });
        Schema::create('server_optimizer_findings', function (Blueprint $table) {
            $table->id();
            $table->foreignId('run_id')->constrained('server_optimizer_runs')->cascadeOnDelete();
            $table->string('rule_id')->nullable();
            $table->string('severity', 16);
            $table->string('title');
            $table->text('explanation');
            $table->string('impact', 32)->nullable();
            $table->boolean('gameplay_change')->default(false);
            $table->boolean('restart_required')->default(false);
            $table->string('source')->nullable();
            $table->json('evidence')->nullable();
            $table->json('recommendation')->nullable();
            $table->boolean('ignored')->default(false);
            $table->timestamps();
        });
        Schema::create('server_optimizer_snapshots', function (Blueprint $table) {
            $table->id();
            $table->unsignedInteger('server_id');
            $table->foreign('server_id')->references('id')->on('servers')->cascadeOnDelete();
            $table->foreignId('finding_id')->nullable()->constrained('server_optimizer_findings')->nullOnDelete();
            $table->string('path');
            $table->longText('contents');
            $table->timestamp('restored_at')->nullable();
            $table->timestamps();
        });
    }
    public function down(): void
    {
        Schema::dropIfExists('server_optimizer_snapshots');
        Schema::dropIfExists('server_optimizer_findings');
        Schema::dropIfExists('server_optimizer_runs');
    }
};
