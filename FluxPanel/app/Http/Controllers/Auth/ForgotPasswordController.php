<?php

namespace Pterodactyl\Http\Controllers\Auth;

use Illuminate\Http\Request;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\Password;
use Pterodactyl\Http\Controllers\Controller;
use Pterodactyl\Events\Auth\FailedPasswordReset;
use Illuminate\Foundation\Auth\SendsPasswordResetEmails;

class ForgotPasswordController extends Controller
{
    use SendsPasswordResetEmails;

    /**
     * Get the response for a failed password reset link.
     */
    protected function sendResetLinkFailedResponse(Request $request, $response): JsonResponse
    {
        event(new FailedPasswordReset($request->ip(), $request->input('email')));

        // Flux deliberately gives the customer a useful correction here. The
        // endpoint remains rate-limited and protected by CAPTCHA, while an
        // unknown address must not pretend that an email was sent.
        return response()->json([
            'errors' => [[
                'code' => 'EmailNotRegistered',
                'status' => '422',
                'detail' => 'No account is registered with this email address.',
            ]],
        ], 422);
    }

    /**
     * Get the response for a successful password reset link.
     *
     * @param string $response
     */
    protected function sendResetLinkResponse(Request $request, $response): JsonResponse
    {
        return response()->json([
            'status' => trans($response),
        ]);
    }
}
