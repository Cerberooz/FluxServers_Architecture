<?php

namespace Pterodactyl\Http\Controllers\Admin;

use Pterodactyl\Http\Controllers\Controller;
use Pterodactyl\Models\SupportTicket;

class SupportTicketController extends Controller
{
    public function index()
    {
        return view('admin.support.index', [
            'tickets' => SupportTicket::query()->with('user')->latest()->paginate(50),
        ]);
    }
}
