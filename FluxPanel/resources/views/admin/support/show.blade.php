@extends('layouts.admin')
@section('title', 'Support Ticket #' . $ticket->id)
@section('content-header')
    <h1>Support Ticket #{{ $ticket->id }} <small>{{ $ticket->subject }}</small></h1>
@endsection
@section('content')
<div class="row">
    <div class="col-sm-8">
        <div class="box box-primary">
            <div class="box-header with-border"><h3 class="box-title">{{ $ticket->subject }}</h3></div>
            <div class="box-body">
                @foreach($ticket->messages as $message)
                    <div style="border: 1px solid #ddd; border-radius: 4px; padding: 12px; margin-bottom: 12px; background: {{ $message->is_admin ? '#f0f7ff' : '#fff' }};">
                        <strong>{{ $message->is_admin ? 'Fluid Support' : ($message->user?->username ?: 'Customer') }}</strong>
                        <small class="text-muted pull-right">{{ $message->created_at }}</small>
                        <div style="white-space: pre-wrap; margin-top: 8px;">{{ $message->body }}</div>
                    </div>
                @endforeach
                <form method="POST" action="{{ route('admin.support.message', ['ticket' => $ticket]) }}">
                    @csrf
                    <div class="form-group"><label for="body">Reply</label><textarea id="body" name="body" class="form-control" rows="6" maxlength="10000" required @if($ticket->status === 'closed') disabled @endif></textarea></div>
                    <button class="btn btn-primary" type="submit" @if($ticket->status === 'closed') disabled @endif>Send reply</button>
                </form>
            </div>
        </div>
    </div>
    <div class="col-sm-4">
        <div class="box box-default">
            <div class="box-header with-border"><h3 class="box-title">Ticket details</h3></div>
            <div class="box-body">
                <p><strong>Customer:</strong> {{ $ticket->user?->username }}</p>
                <p><strong>Email:</strong> {{ $ticket->email }}</p>
                <form method="POST" action="{{ route('admin.support.status', ['ticket' => $ticket]) }}">
                    @csrf @method('PATCH')
                    <label for="status">Status</label>
                    <select id="status" name="status" class="form-control" onchange="this.form.submit()">
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
