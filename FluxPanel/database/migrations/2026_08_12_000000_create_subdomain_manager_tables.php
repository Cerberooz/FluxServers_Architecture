<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('subdomain_domains', function (Blueprint $table) {
            $table->id();
            $table->string('domain')->unique();
            $table->string('provider')->default('cloudflare');
            $table->string('provider_zone_id');
            $table->boolean('enabled')->default(true);
            $table->json('allowed_egg_ids')->nullable();
            $table->unsignedSmallInteger('max_per_server')->default(1);
            $table->json('reserved_labels')->nullable();
            $table->timestamps();
        });

        Schema::create('server_subdomains', function (Blueprint $table) {
            $table->id();
            // The existing servers table predates Laravel's big ID convention.
            $table->unsignedInteger('server_id');
            $table->foreign('server_id')->references('id')->on('servers')->cascadeOnDelete();
            $table->foreignId('domain_id')->constrained('subdomain_domains')->restrictOnDelete();
            $table->string('label', 63);
            $table->string('hostname')->unique();
            $table->string('status', 16)->default('pending');
            $table->unsignedBigInteger('allocation_id')->nullable();
            $table->string('target_ip')->nullable();
            $table->unsignedSmallInteger('target_port')->nullable();
            $table->string('a_record_id')->nullable();
            $table->string('srv_record_id')->nullable();
            $table->text('last_error')->nullable();
            $table->timestamp('last_synced_at')->nullable();
            $table->timestamps();
            $table->unique(['domain_id', 'label']);
            $table->index(['server_id', 'status']);
        });

        Schema::create('subdomain_dns_operations', function (Blueprint $table) {
            $table->id();
            $table->foreignId('subdomain_id')->nullable()->constrained('server_subdomains')->nullOnDelete();
            $table->string('operation', 24);
            $table->string('status', 16);
            $table->unsignedTinyInteger('attempt')->default(1);
            $table->text('message')->nullable();
            $table->json('context')->nullable();
            $table->timestamps();
            $table->index(['status', 'created_at']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('subdomain_dns_operations');
        Schema::dropIfExists('server_subdomains');
        Schema::dropIfExists('subdomain_domains');
    }
};
