import http from '@/api/http';

export interface BillingService {
    identifier: string | null;
    plan_name: string | null;
    node_name: string | null;
    status: string;
    ip_address: string | null;
    created_at: string | null;
    expires_at: string | null;
}

export interface BillingInvoice {
    public_id: string;
    status: string;
    currency: string;
    total_cents: number;
    created_at: string;
    paid_at: string | null;
    payment_provider: string | null;
    description: string;
}

export interface BillingData {
    services: BillingService[];
    invoices: BillingInvoice[];
    summary: { monthly_total_cents: number; next_billing_date: string | null };
}

export default (): Promise<BillingData> => http.get('/api/client/billing').then(({ data }) => data);
