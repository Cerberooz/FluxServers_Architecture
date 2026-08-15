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
            'select s.pelican_server_identifier as identifier, s.plan_name, s.node_name, s.status,
                    s.ip_address, s.created_at, s.expires_at, p.price as monthly_price
             from server_record s left join game_plan p on p.id = s.plan_id
             where s.user_id = ? and s.status <> ? order by s.created_at desc',
            [$user->id, 'Deleted']
        );

        $invoices = $connection->select(
            'select o.public_id, o.status, o.currency, o.total_cents, o.created_at,
                    o.paid_at, o.payment_provider,
                    coalesce(string_agg(i.name, \' , \' order by i.id), \'Service\') as description
             from customer_order o left join customer_order_item i on i.order_id = o.id
             where o.user_id = ? group by o.id order by o.created_at desc limit 50',
            [$user->id]
        );

        $monthlyTotal = collect($services)->sum(fn ($service) => (float) ($service->monthly_price ?? 0));

        return [
            'services' => $services,
            'invoices' => $invoices,
            'summary' => ['monthly_total_cents' => (int) round($monthlyTotal * 100)],
        ];
    }
}
