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

export interface BillingPagination {
    page: number;
    per_page: number;
    total: number;
    total_pages: number;
}

export interface BillingPage<T> {
    items: T[];
    pagination: BillingPagination;
}

export interface BillingData {
    services: BillingPage<BillingService>;
    invoices: BillingPage<BillingInvoice>;
    summary: { monthly_total_cents: number; next_billing_date: string | null };
}

export interface BillingQuery {
    services_page: number;
    invoices_page: number;
    per_page: number;
}

export default (query: BillingQuery): Promise<BillingData> => http.get('/api/client/billing', { params: query }).then(({ data }) => data);
