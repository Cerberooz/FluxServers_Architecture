import http from '@/api/http';

export default (server: string): Promise<number | null> =>
    http.get(`/api/client/servers/${server}/node-uptime`).then(({ data }) => {
        const uptime = Number(data?.uptime);

        return Number.isFinite(uptime) && uptime >= 0 ? uptime : null;
    });
