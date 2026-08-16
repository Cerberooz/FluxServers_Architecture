<?php

namespace Pterodactyl\Http\Controllers\Auth;

use Illuminate\Http\RedirectResponse;
use Pterodactyl\Models\User;
use Pterodactyl\Http\Controllers\Controller;

class VerifyEmailController extends Controller
{
    public function __invoke(int $id, string $hash): RedirectResponse
    {
        $user = User::query()->findOrFail($id);

        abort_unless(hash_equals(sha1($user->getEmailForVerification()), $hash), 403);

        if (!$user->hasVerifiedEmail()) {
            $user->markEmailAsVerified();
        }

        return redirect('/auth/email/verified');
    }
}
