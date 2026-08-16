@extends('layouts.admin')
@section('title', 'Support Tickets')
@section('content-header')<h1>Support Tickets<small>Customer support requests submitted through the panel.</small></h1>@endsection
@section('content')
<div class="box box-primary">
    <div class="box-header with-border"><h3 class="box-title">Customer tickets</h3></div>
    <div class="table-responsive">
        <table class="table table-hover">
            <tr><th>Created</th><th>Customer</th><th>Email</th><th>Subject</th><th>Details</th><th>Status</th></tr>
            @forelse($tickets as $ticket)
                <tr style="cursor: pointer;" onclick="window.location='{{ route('admin.support.show', ['ticket' => $ticket]) }}'">
                    <td>{{ $ticket->created_at }}</td>
                    <td>{{ $ticket->user?->name ?: $ticket->user?->username }}</td>
                    <td>{{ $ticket->email }}</td>
                    <td><a href="{{ route('admin.support.show', ['ticket' => $ticket]) }}">{{ $ticket->subject }}</a></td>
                    <td style="white-space: pre-wrap; max-width: 420px;">{{ $ticket->details }}</td>
                    <td><span class="label label-{{ $ticket->status === 'open' ? 'warning' : ($ticket->status === 'resolved' ? 'success' : 'info') }}">{{ str_replace('_', ' ', ucfirst($ticket->status)) }}</span></td>
                </tr>
            @empty
                <tr><td colspan="6">No support tickets have been submitted.</td></tr>
            @endforelse
        </table>
    </div>
    <div class="box-footer">{{ $tickets->links() }}</div>
</div>
@endsection
