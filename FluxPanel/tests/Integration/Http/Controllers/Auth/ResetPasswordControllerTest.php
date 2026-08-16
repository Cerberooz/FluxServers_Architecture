<?php

namespace Pterodactyl\Tests\Integration\Http\Controllers\Auth;

use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\Password;
use Pterodactyl\Models\User;
use Pterodactyl\Tests\Integration\Http\HttpTestCase;

class ResetPasswordControllerTest extends HttpTestCase
{
    public function testResettingAnUnverifiedAccountDoesNotAuthenticateIt(): void
    {
        $user = User::factory()->create(['email_verified_at' => null]);
        $token = Password::broker()->createToken($user);

        $this->postJson('/auth/password/reset', [
            'email' => $user->email,
            'token' => $token,
            'password' => 'New_Password1',
            'password_confirmation' => 'New_Password1',
        ])
            ->assertOk()
            ->assertJsonPath('send_to_login', true);

        $this->assertGuest();
        $this->assertTrue(Hash::check('New_Password1', $user->fresh()->password));
    }

    public function testResettingAVerifiedAccountAuthenticatesIt(): void
    {
        $user = User::factory()->create(['email_verified_at' => now()]);
        $token = Password::broker()->createToken($user);

        $this->postJson('/auth/password/reset', [
            'email' => $user->email,
            'token' => $token,
            'password' => 'New_Password1',
            'password_confirmation' => 'New_Password1',
        ])
            ->assertOk()
            ->assertJsonPath('send_to_login', false);

        $this->assertAuthenticatedAs($user);
    }
}
