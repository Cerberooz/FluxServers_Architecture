<?php

namespace Pterodactyl\Http\Controllers\Auth;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;
use Pterodactyl\Models\User;

class ResendEmailVerificationController extends AbstractLoginController
{
    /**
     * Re-send an activation link without revealing whether an account exists.
     */
    public function __invoke(Request $request): JsonResponse
    {
        $data = $request->validate([
            'email' => ['required', 'email'],
        ]);

        $user = User::query()->where('email', $data['email'])->first();

        if ($user && !$user->hasVerifiedEmail()) {
            try {
                $user->sendEmailVerificationNotification();
            } catch (\Throwable $exception) {
                Log::error('Unable to resend an email verification notification.', [
                    'user_id' => $user->id,
                    'exception' => $exception->getMessage(),
                ]);

                return new JsonResponse([
                    'message' => 'We could not send the activation email right now. Please try again shortly.',
                ], 503);
            }
        }

        return new JsonResponse([
            'data' => [
                'sent' => true,
            ],
        ]);
    }
}
