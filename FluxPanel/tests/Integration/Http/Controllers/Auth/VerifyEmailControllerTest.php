<?php

namespace Pterodactyl\Tests\Integration\Http\Controllers\Auth;

use Illuminate\Support\Facades\URL;
use Pterodactyl\Models\User;
use Pterodactyl\Tests\Integration\Http\HttpTestCase;

class VerifyEmailControllerTest extends HttpTestCase
{
    public function testSignedVerificationLinkActivatesTheAccountAndShowsConfirmation(): void
    {
        $user = User::factory()->create(['email_verified_at' => null]);
        $url = URL::temporarySignedRoute('verification.verify', now()->addMinutes(30), [
            'id' => $user->id,
            'hash' => sha1($user->getEmailForVerification()),
        ]);

        $this->get($url)
            ->assertRedirect('/auth/email/verified');

        $this->assertNotNull($user->fresh()->email_verified_at);
    }
}
