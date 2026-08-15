import http from '@/api/http';

export interface SupportTicket {
    id: number;
    email: string;
    subject: string;
    details: string;
    status: string;
    created_at: string;
    updated_at: string;
}

export interface SupportData {
    tickets: SupportTicket[];
    pagination: {
        page: number;
        per_page: number;
        total: number;
        total_pages: number;
    };
}

export interface SupportTicketInput {
    email: string;
    subject: string;
    details: string;
}

export const getSupport = (): Promise<SupportData> => http.get('/api/client/support').then(({ data }) => data);
export const createSupportTicket = (input: SupportTicketInput): Promise<{ ticket: SupportTicket }> => http.post('/api/client/support', input).then(({ data }) => data);
