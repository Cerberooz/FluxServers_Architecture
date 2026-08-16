<?php

namespace Pterodactyl\Http\Controllers\Api\Client;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Pterodactyl\Models\SupportTicket;
use Pterodactyl\Models\SupportTicketMessage;

class SupportController extends ClientApiController
{
    public function index(Request $request): JsonResponse
    {
        $tickets = SupportTicket::query()
            ->where('user_id', $request->user()->id)
            ->with('messages:id,ticket_id,is_admin,customer_read_at')
            ->latest()
            ->paginate(25);

        return response()->json([
            'tickets' => collect($tickets->items())->map(function (SupportTicket $ticket): array {
                $data = $ticket->toArray();
                $data['unread_count'] = $ticket->messages->where('is_admin', true)->whereNull('customer_read_at')->count();
                unset($data['messages']);
                return $data;
            })->values(),
            'pagination' => [
                'page' => $tickets->currentPage(),
                'per_page' => $tickets->perPage(),
                'total' => $tickets->total(),
                'total_pages' => $tickets->lastPage(),
            ],
        ]);
    }

    public function show(Request $request, SupportTicket $ticket): JsonResponse
    {
        abort_unless($ticket->user_id === $request->user()->id, 404);

        $ticket->messages()
            ->where('is_admin', true)
            ->whereNull('customer_read_at')
            ->update(['customer_read_at' => now()]);

        return response()->json($this->ticketPayload($ticket));
    }

    public function store(Request $request): JsonResponse
    {
        $data = $request->validate([
            'email' => ['required', 'email', 'max:191'],
            'subject' => ['required', 'string', 'max:191'],
            'details' => ['required', 'string', 'max:10000'],
        ]);

        $ticket = DB::transaction(function () use ($data, $request): SupportTicket {
            $ticket = SupportTicket::query()->create([
                ...$data,
                'user_id' => $request->user()->id,
                'status' => SupportTicket::STATUS_OPEN,
            ]);
            $ticket->messages()->create([
                'user_id' => $request->user()->id,
                'is_admin' => false,
                'body' => $data['details'],
            ]);
            return $ticket;
        });

        return response()->json(['ticket' => $ticket], 201);
    }

    public function message(Request $request, SupportTicket $ticket): JsonResponse
    {
        abort_unless($ticket->user_id === $request->user()->id, 404);
        abort_if($ticket->status === SupportTicket::STATUS_CLOSED, 409, 'This ticket is closed.');

        $data = $request->validate(['body' => ['required', 'string', 'max:10000']]);
        $message = $ticket->messages()->create([
            'user_id' => $request->user()->id,
            'is_admin' => false,
            'body' => $data['body'],
        ]);
        if ($ticket->status === SupportTicket::STATUS_RESOLVED) {
            $ticket->update(['status' => SupportTicket::STATUS_OPEN]);
        }

        return response()->json(['message' => $message, ...$this->ticketPayload($ticket->fresh())]);
    }

    public function close(Request $request, SupportTicket $ticket): JsonResponse
    {
        abort_unless($ticket->user_id === $request->user()->id, 404);
        abort_if($ticket->status === SupportTicket::STATUS_CLOSED, 409, 'This ticket is already closed.');

        $ticket->update(['status' => SupportTicket::STATUS_CLOSED]);
        return response()->json($this->ticketPayload($ticket->fresh()));
    }

    private function ticketPayload(SupportTicket $ticket): array
    {
        $ticket->load('messages.user');
        return [
            'ticket' => tap($ticket, function (SupportTicket $ticket): void {
                $ticket->setAttribute('unread_count', $ticket->messages->where('is_admin', true)->whereNull('customer_read_at')->count());
            }),
            'messages' => $ticket->messages->map(fn (SupportTicketMessage $message) => [
                'id' => $message->id,
                'body' => $message->body,
                'is_admin' => (bool) $message->is_admin,
                'author' => $message->user?->username ?? ($message->is_admin ? 'Fluid Support' : 'Customer'),
                'role' => $message->is_admin ? 'Admin' : 'Customer',
                'created_at' => $message->created_at,
            ])->values(),
        ];
    }
}
