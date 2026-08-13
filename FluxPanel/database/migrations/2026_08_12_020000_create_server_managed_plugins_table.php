<?php
use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;
return new class extends Migration {
    public function up(): void { Schema::create('server_managed_plugins', function (Blueprint $table) { $table->id(); $table->unsignedInteger('server_id'); $table->foreign('server_id')->references('id')->on('servers')->cascadeOnDelete(); $table->string('filename'); $table->string('project_id')->nullable(); $table->string('version_id')->nullable(); $table->string('sha512', 128)->nullable(); $table->boolean('disabled')->default(false); $table->timestamps(); $table->unique(['server_id', 'filename']); }); }
    public function down(): void { Schema::dropIfExists('server_managed_plugins'); }
};
