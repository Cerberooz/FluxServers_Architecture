import http from '@/api/http';

export default (email: string): Promise<void> => {
    return http.get('/sanctum/csrf-cookie')
        .then(() => http.post('/auth/email/verification-notification', { email }))
        .then(() => undefined);
};
