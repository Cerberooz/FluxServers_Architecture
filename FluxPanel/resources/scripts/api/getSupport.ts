import http from '@/api/http';

export interface SupportTicket {
    id: number;
    email: string;
    subject: string;
    details: string;
    status: string;
    created_at: string;
    updated_at: string;
    unread_count: number;
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

export interface SupportMessage {
    id: number;
    body: string;
    is_admin: boolean;
    author: string;
    created_at: string;
}

export interface SupportThread {
    ticket: SupportTicket;
    messages: SupportMessage[];
}

export interface SupportTicketInput {
    email: string;
    subject: string;
    details: string;
}

export const getSupport = (): Promise<SupportData> => http.get('/api/client/support').then(({ data }) => data);
export const createSupportTicket = (input: SupportTicketInput): Promise<{ ticket: SupportTicket }> => http.post('/api/client/support', input).then(({ data }) => data);
export const getSupportThread = (id: number): Promise<SupportThread> => http.get(`/api/client/support/${id}`).then(({ data }) => data);
export const replyToSupportTicket = (id: number, body: string): Promise<SupportThread> => http.post(`/api/client/support/${id}/messages`, { body }).then(({ data }) => data);
