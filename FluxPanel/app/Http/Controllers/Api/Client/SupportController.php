<?php

namespace Pterodactyl\Http\Controllers\Api\Client;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Pterodactyl\Models\SupportTicket;

class SupportController extends ClientApiController
{
    public function index(Request $request): JsonResponse
    {
        $tickets = SupportTicket::query()
            ->where('user_id', $request->user()->id)
            ->latest()
            ->paginate(25);

        return response()->json([
            'tickets' => $tickets->items(),
            'pagination' => [
                'page' => $tickets->currentPage(),
                'per_page' => $tickets->perPage(),
                'total' => $tickets->total(),
                'total_pages' => $tickets->lastPage(),
            ],
        ]);
    }

    public function store(Request $request): JsonResponse
    {
        $data = $request->validate([
            'email' => ['required', 'email', 'max:191'],
            'subject' => ['required', 'string', 'max:191'],
            'details' => ['required', 'string', 'max:10000'],
        ]);

        $ticket = SupportTicket::query()->create([
            ...$data,
            'user_id' => $request->user()->id,
            'status' => SupportTicket::STATUS_OPEN,
        ]);

        return response()->json(['ticket' => $ticket], 201);
    }
}
