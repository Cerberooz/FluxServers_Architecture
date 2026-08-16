@extends('layouts.admin')
@section('title', 'Support Ticket #' . $ticket->id)
@section('content-header')
    <h1>Support Ticket #{{ $ticket->id }} <small>{{ $ticket->subject }}</small></h1>
@endsection
@section('content')
<div class="row">
    <div class="col-sm-8">
        <div class="box box-primary" style="background:#111827; border-color:#374151; color:#e5e7eb;">
            <div class="box-header with-border" style="background:#111827; border-color:#374151; color:#f3f4f6;"><h3 class="box-title">{{ $ticket->subject }}</h3></div>
            <div class="box-body" style="background:#111827; color:#d1d5db;">
                @foreach($ticket->messages as $message)
                    <div style="border: 1px solid {{ $message->is_admin ? '#1d4ed8' : '#374151' }}; border-radius: 6px; padding: 14px; margin-bottom: 12px; background: {{ $message->is_admin ? '#172554' : '#1f2937' }}; color: #e5e7eb;">
                        <strong>{{ $message->is_admin ? 'Fluid Support' : ($message->user?->username ?: 'Customer') }} <span style="display:inline-block; margin-left:6px; border-radius:4px; padding:2px 6px; background:#374151; color:#d1d5db; font-size:11px; font-weight:600;">[{{ $message->is_admin ? 'Admin' : 'Customer' }}]</span></strong>
                        <small style="color:#9ca3af;" class="pull-right">{{ $message->created_at }}</small>
                        <div style="white-space: pre-wrap; margin-top: 8px; color:#f3f4f6;">{{ $message->body }}</div>
                    </div>
                @endforeach
                <form method="POST" action="{{ route('admin.support.message', ['ticket' => $ticket]) }}">
                    @csrf
                    <div class="form-group"><label for="body" style="color:#e5e7eb;">Reply</label><textarea id="body" name="body" class="form-control" rows="6" maxlength="10000" required style="background:#1f2937; border-color:#4b5563; color:#f3f4f6;" @if($ticket->status === 'closed') disabled @endif></textarea></div>
                    <button class="btn btn-primary" type="submit" @if($ticket->status === 'closed') disabled @endif>Send reply</button>
                </form>
            </div>
        </div>
    </div>
    <div class="col-sm-4">
        <div class="box box-default" style="background:#111827; border-color:#374151; color:#e5e7eb;">
            <div class="box-header with-border" style="background:#111827; border-color:#374151; color:#f3f4f6;"><h3 class="box-title">Ticket details</h3></div>
            <div class="box-body" style="background:#111827; color:#d1d5db;">
                <p><strong>Customer:</strong> {{ $ticket->user?->username }}</p>
                <p><strong>Email:</strong> {{ $ticket->email }}</p>
                <form method="POST" action="{{ route('admin.support.status', ['ticket' => $ticket]) }}">
                    @csrf @method('PATCH')
                    <label for="status">Status</label>
                    <select id="status" name="status" class="form-control" style="background:#1f2937; border-color:#4b5563; color:#f3f4f6;" onchange="this.form.submit()" @if($ticket->status === 'closed') disabled @endif>
                        @foreach(['open' => 'Open', 'in_progress' => 'In Progress', 'resolved' => 'Resolved', 'closed' => 'Closed'] as $value => $label)
                            <option value="{{ $value }}" @selected($ticket->status === $value)>{{ $label }}</option>
                        @endforeach
                    </select>
                </form>
            </div>
        </div>
        <a href="{{ route('admin.support') }}" class="btn btn-default">Back to tickets</a>
    </div>
</div>
@endsection
