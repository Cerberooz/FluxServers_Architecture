<?php

namespace PterodactylServices\Billing;

use Illuminate\Support\Facades\DB;

/** Read-only adapter for the FluxWeb/Supabase billing ledger. */
class WebBillingService
{
    public function forEmail(string $email, int $servicesPage = 1, int $invoicesPage = 1, int $perPage = 5): array
    {
        $connection = DB::connection('web_pgsql');
        $servicesPage = max(1, $servicesPage);
        $invoicesPage = max(1, $invoicesPage);
        $perPage = min(50, max(1, $perPage));
        $user = $connection->selectOne('select id from "user" where lower(email) = lower(?) limit 1', [$email]);

        if (!$user) {
            return [
                'services' => $this->page([], $servicesPage, $perPage, 0),
                'invoices' => $this->page([], $invoicesPage, $perPage, 0),
                'summary' => ['monthly_total_cents' => 0, 'next_billing_date' => null],
            ];
        }

        $serviceTotal = (int) ($connection->selectOne(
            'select count(*) as total from server_record where user_id = ? and status <> ?',
            [$user->id, 'Deleted']
        )->total ?? 0);
        $serviceOffset = ($servicesPage - 1) * $perPage;
        $services = $connection->select(
            'select pelican_server_identifier as identifier, plan_name, node_name, status,
                    ip_address, created_at, expires_at
             from server_record
             where user_id = ? and status <> ? order by created_at desc
             limit ? offset ?',
            [$user->id, 'Deleted', $perPage, $serviceOffset]
        );

        $invoiceTotal = (int) ($connection->selectOne(
            'select count(*) as total from customer_order where user_id = ?',
            [$user->id]
        )->total ?? 0);
        $invoiceOffset = ($invoicesPage - 1) * $perPage;
        $orders = $connection->select(
            'select id, public_id, status, currency, total_cents, created_at, paid_at, payment_provider
             from customer_order where user_id = ? order by created_at desc
             limit ? offset ?',
            [$user->id, $perPage, $invoiceOffset]
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

        $monthlyTotal = (int) ($connection->selectOne(
            "select coalesce(sum(total_cents), 0) as total from customer_order
             where user_id = ? and status in ('paid', 'provisioning', 'completed')",
            [$user->id]
        )->total ?? 0);
        $nextBillingDate = $connection->selectOne(
            'select min(expires_at) as next_billing_date from server_record
             where user_id = ? and status <> ? and expires_at is not null',
            [$user->id, 'Deleted']
        )->next_billing_date ?? null;

        return [
            'services' => $this->page($services, $servicesPage, $perPage, $serviceTotal),
            'invoices' => $this->page($invoices, $invoicesPage, $perPage, $invoiceTotal),
            'summary' => [
                'monthly_total_cents' => $monthlyTotal,
                'next_billing_date' => $nextBillingDate,
            ],
        ];
    }

    private function page(array $items, int $page, int $perPage, int $total): array
    {
        return [
            'items' => $items,
            'pagination' => [
                'page' => $page,
                'per_page' => $perPage,
                'total' => $total,
                'total_pages' => $total > 0 ? (int) ceil($total / $perPage) : 1,
            ],
        ];
    }
}
