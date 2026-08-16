<?php

namespace Pterodactyl\Http\Controllers\Admin;

use Pterodactyl\Http\Controllers\Controller;
use Pterodactyl\Models\SupportTicket;
use Illuminate\Http\Request;

class SupportTicketController extends Controller
{
    public function index()
    {
        return view('admin.support.index', [
            'tickets' => SupportTicket::query()->with('user')->latest()->paginate(50),
        ]);
    }

    public function show(SupportTicket $ticket)
    {
        $ticket->load(['user', 'messages.user']);
        return view('admin.support.show', compact('ticket'));
    }

    public function message(Request $request, SupportTicket $ticket)
    {
        abort_if($ticket->status === SupportTicket::STATUS_CLOSED, 409, 'This ticket is closed.');
        $data = $request->validate(['body' => ['required', 'string', 'max:10000']]);
        $ticket->messages()->create([
            'user_id' => $request->user()->id,
            'is_admin' => true,
            'body' => $data['body'],
        ]);
        if ($ticket->status === SupportTicket::STATUS_OPEN) {
            $ticket->update(['status' => SupportTicket::STATUS_IN_PROGRESS]);
        }
        return redirect()->route('admin.support.show', ['ticket' => $ticket])->with('success', 'Reply sent.');
    }

    public function status(Request $request, SupportTicket $ticket)
    {
        $data = $request->validate([
            'status' => ['required', 'in:open,in_progress,resolved,closed'],
        ]);
        if ($ticket->status === SupportTicket::STATUS_CLOSED && $data['status'] !== SupportTicket::STATUS_CLOSED) {
            abort(409, 'Closed tickets cannot be reopened.');
        }
        $ticket->update(['status' => $data['status']]);
        return redirect()->route('admin.support.show', ['ticket' => $ticket])->with('success', 'Ticket status updated.');
    }
}
