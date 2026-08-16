<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('support_ticket_messages', function (Blueprint $table) {
            $table->id();
            $table->unsignedBigInteger('ticket_id');
            $table->unsignedInteger('user_id')->nullable();
            $table->boolean('is_admin')->default(false);
            $table->text('body');
            $table->dateTime('customer_read_at')->nullable();
            $table->timestamps();

            $table->foreign('ticket_id')->references('id')->on('support_tickets')->cascadeOnDelete();
            $table->foreign('user_id')->references('id')->on('users')->nullOnDelete();
            $table->index(['ticket_id', 'created_at']);
        });

        // Preserve the original ticket description as the first message.
        DB::table('support_tickets')->orderBy('id')->each(function (object $ticket): void {
            DB::table('support_ticket_messages')->insert([
                'ticket_id' => $ticket->id,
                'user_id' => $ticket->user_id,
                'is_admin' => false,
                'body' => $ticket->details,
                'customer_read_at' => $ticket->created_at,
                'created_at' => $ticket->created_at,
                'updated_at' => $ticket->updated_at,
            ]);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('support_ticket_messages');
    }
};
