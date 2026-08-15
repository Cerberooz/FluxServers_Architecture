<?php

namespace Pterodactyl\Http\Controllers\Api\Client;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;
use Throwable;
use Pterodactyl\Services\Billing\WebBillingService;

class BillingController extends ClientApiController
{
    public function __construct(private WebBillingService $billing)
    {
        parent::__construct();
    }

    public function index(Request $request): JsonResponse
    {
        try {
            return response()->json($this->billing->forEmail(
                $request->user()->email,
                (int) $request->query('services_page', 1),
                (int) $request->query('invoices_page', 1),
                (int) $request->query('per_page', 5)
            ));
        } catch (Throwable $exception) {
            Log::error('Unable to read Web billing data from PostgreSQL.', ['message' => $exception->getMessage()]);
            return response()->json(['message' => 'Billing is temporarily unavailable.', 'services' => [], 'invoices' => []], 503);
        }
    }
}
