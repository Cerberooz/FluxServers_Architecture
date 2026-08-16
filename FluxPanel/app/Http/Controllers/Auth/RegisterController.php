<?php

namespace Pterodactyl\Http\Controllers\Auth;

use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\Log;
use Pterodactyl\Http\Requests\Auth\RegisterRequest;
use Pterodactyl\Services\Users\UserCreationService;

class RegisterController extends AbstractLoginController
{
    public function __construct(private UserCreationService $creationService)
    {
        parent::__construct();
    }

    /**
     * Create a normal user account and sign the user in.
     *
     * @throws \Exception
     * @throws \Pterodactyl\Exceptions\Model\DataValidationException
     */
    public function __invoke(RegisterRequest $request): JsonResponse
    {
        $user = $this->creationService->handle([
            'email' => $request->input('email'),
            'username' => $request->input('username'),
            'name_first' => $request->input('name_first'),
            'name_last' => $request->input('name_last'),
            'password' => $request->input('password'),
            'root_admin' => false,
            'email_verified_at' => null,
        ]);

        try {
            $user->sendEmailVerificationNotification();
        } catch (\Throwable $exception) {
            // The account must remain unverified. The activation screen provides a
            // resend action, rather than sending an authenticated user into the panel.
            Log::error('Unable to send an email verification notification.', [
                'user_id' => $user->id,
                'exception' => $exception->getMessage(),
            ]);

            return new JsonResponse([
                'data' => [
                    'complete' => false,
                    'verification_required' => true,
                    'email_sent' => false,
                ],
            ]);
        }

        return new JsonResponse([
            'data' => [
                'complete' => false,
                'verification_required' => true,
                'email_sent' => true,
                'intended' => '/auth/login',
            ],
        ]);
    }
}
