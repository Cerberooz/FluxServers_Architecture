import http from '@/api/http';

export default (server: string): Promise<number | null> =>
    http.get(`/api/client/servers/${server}/node-uptime`).then(({ data }) => data.uptime ?? null);
