import http from '@/api/http';

export interface DashboardStats {
    total: number;
    online: number;
    offline: number;
    playersOnline: number | null;
    playersQueried: number;
    averageUptime: number | null;
}

export default (type?: 'admin-all'): Promise<DashboardStats> => http.get('/api/client/dashboard/stats', { params: { type } }).then(({ data }) => ({
    total: data.total,
    online: data.online,
    offline: data.offline,
    playersOnline: data.players_online,
    playersQueried: data.players_queried,
    averageUptime: data.average_uptime,
}));
