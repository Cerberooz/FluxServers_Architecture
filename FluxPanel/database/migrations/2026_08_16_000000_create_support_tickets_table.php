<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        // An earlier deployment could create this table before failing while
        // adding its foreign key. Preserve that table and let Laravel record
        // this migration instead of attempting to create it again.
        if (Schema::hasTable('support_tickets')) {
            return;
        }

        Schema::create('support_tickets', function (Blueprint $table) {
            $table->id();
            // Fluid/Pterodactyl's users.id is an UNSIGNED INT created with
            // increments(), not Laravel's newer UNSIGNED BIGINT foreignId().
            $table->unsignedInteger('user_id');
            $table->foreign('user_id')->references('id')->on('users')->cascadeOnDelete();
            $table->string('email', 191);
            $table->string('subject', 191);
            $table->text('details');
            $table->string('status', 32)->default('open')->index();
            $table->text('admin_notes')->nullable();
            $table->timestamps();
            $table->index(['user_id', 'created_at']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('support_tickets');
    }
};
