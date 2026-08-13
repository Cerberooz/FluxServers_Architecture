<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

class AddNullableFieldLastrun extends Migration
{
    /**
     * Run the migrations.
     */
    public function up()
    {
        if (DB::connection()->getDriverName() === 'sqlite') {
            Schema::table('tasks', function (Blueprint $table) {
                $table->timestamp('last_run')->nullable()->change();
            });

            return;
        }

        $table = DB::getQueryGrammar()->wrapTable('tasks');
        DB::statement('ALTER TABLE ' . $table . ' CHANGE `last_run` `last_run` TIMESTAMP NULL;');
    }

    /**
     * Reverse the migrations.
     */
    public function down()
    {
        if (DB::connection()->getDriverName() === 'sqlite') {
            Schema::table('tasks', function (Blueprint $table) {
                $table->timestamp('last_run')->nullable(false)->change();
            });

            return;
        }

        $table = DB::getQueryGrammar()->wrapTable('tasks');
        DB::statement('ALTER TABLE ' . $table . ' CHANGE `last_run` `last_run` TIMESTAMP;');
    }
}
