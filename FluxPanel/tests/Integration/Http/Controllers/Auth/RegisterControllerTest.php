<?php

namespace Pterodactyl\Tests\Integration\Http\Controllers\Auth;

use Illuminate\Auth\Notifications\VerifyEmail;
use Illuminate\Support\Facades\Notification;
use Pterodactyl\Models\User;
use Pterodactyl\Tests\Integration\Http\HttpTestCase;

class RegisterControllerTest extends HttpTestCase
{
    protected function setUp(): void
    {
        parent::setUp();

        config()->set('recaptcha.enabled', false);
        Notification::fake();
    }

    public function testRegistrationCreatesAnUnverifiedAccountAndSendsAnActivationEmail(): void
    {
        $email = 'activation-test@example.com';

        $this->postJson(route('auth.post.register'), [
            'email' => $email,
            'username' => 'activation_test',
            'name_first' => 'Activation',
            'name_last' => 'Test',
            'password' => 'New_Password1',
            'password_confirmation' => 'New_Password1',
        ])
            ->assertOk()
            ->assertJsonPath('data.complete', false)
            ->assertJsonPath('data.verification_required', true)
            ->assertJsonPath('data.email_sent', true);

        $user = User::query()->where('email', $email)->firstOrFail();

        $this->assertNull($user->email_verified_at);
        $this->assertGuest();
        Notification::assertSentTo($user, VerifyEmail::class);
    }
}
