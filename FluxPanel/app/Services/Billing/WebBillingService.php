<?php

namespace Pterodactyl\Services\Billing;

use Illuminate\Support\Facades\DB;

/** Read-only adapter for the FluxWeb/Supabase billing ledger. */
class WebBillingService
{
    public function forEmail(string $email): array
    {
        $connection = DB::connection('web_pgsql');
        $user = $connection->selectOne('select id from "user" where lower(email) = lower(?) limit 1', [$email]);

        if (!$user) {
            return ['services' => [], 'invoices' => [], 'summary' => ['monthly_total_cents' => 0]];
        }

        $services = $connection->select(
            'select pelican_server_identifier as identifier, plan_name, node_name, status,
                    ip_address, created_at, expires_at
             from server_record
             where user_id = ? and status <> ? order by created_at desc',
            [$user->id, 'Deleted']
        );

        $orders = $connection->select(
            'select id, public_id, status, currency, total_cents, created_at, paid_at, payment_provider
             from customer_order where user_id = ? order by created_at desc limit 50',
            [$user->id]
        );

        $invoices = collect($orders)->map(function ($order) use ($connection) {
            $items = $connection->select(
                'select name from customer_order_item where order_id = ? order by id',
                [$order->id]
            );

            return [
                'public_id' => $order->public_id,
                'status' => $order->status,
                'currency' => $order->currency,
                'total_cents' => $order->total_cents,
                'created_at' => $order->created_at,
                'paid_at' => $order->paid_at,
                'payment_provider' => $order->payment_provider,
                'description' => collect($items)->pluck('name')->join(', ') ?: 'Service',
            ];
        })->values()->all();

        $monthlyTotal = collect($invoices)
            ->filter(fn ($invoice) => in_array($invoice['status'], ['paid', 'provisioning', 'completed'], true))
            ->sum('total_cents');
        $nextBillingDate = collect($services)->pluck('expires_at')->filter()->sort()->first();

        return [
            'services' => $services,
            'invoices' => $invoices,
            'summary' => [
                'monthly_total_cents' => (int) $monthlyTotal,
                'next_billing_date' => $nextBillingDate,
            ],
        ];
    }
}
