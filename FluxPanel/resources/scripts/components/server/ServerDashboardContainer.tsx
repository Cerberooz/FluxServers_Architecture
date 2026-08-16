import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { formatDistanceToNowStrict } from 'date-fns';
import { ServerContext } from '@/state/server';
import ServerContentBlock from '@/components/elements/ServerContentBlock';
import Spinner from '@/components/elements/Spinner';
import getServerResourceUsage, { ServerStats } from '@/api/server/getServerResourceUsage';
import { Server } from '@/api/server/getServer';
import getServerNodeUptime from '@/api/server/getServerNodeUptime';
import { useActivityLogs } from '@/api/server/activity';
import { bytesToString, ip, mbToBytes } from '@/lib/formatters';
import UptimeDuration from '@/components/server/UptimeDuration';

type Timer = ReturnType<typeof setInterval>;

const activityTitle = (event: string) => event.replace(/[:._-]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());

const Detail = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div className={'fluid-dashboard-detail'}>
        <span>{label}</span>
        <strong>{children}</strong>
    </div>
);

const Usage = ({ label, value, percent }: { label: string; value: string; percent: number }) => (
    <div className={'fluid-dashboard-usage'}>
        <div><span>{label}</span><strong>{value}</strong></div>
        <div className={'fluid-dashboard-usage__track'}><i style={{ width: `${Math.max(0, Math.min(percent, 100))}%` }} /></div>
    </div>
);

const ServerDashboard = ({ server }: { server: Server }) => {
    const status = ServerContext.useStoreState((state) => state.status.value);
    const [stats, setStats] = useState<ServerStats | null>(null);
    const [nodeUptime, setNodeUptime] = useState<number | null>(null);
    const interval = useRef<Timer>(null) as React.MutableRefObject<Timer>;
    const { data: activity, isValidating: isActivityLoading } = useActivityLogs(
        { page: 1, perPage: 3, sorts: { timestamp: -1 } },
        { revalidateOnMount: true, revalidateOnFocus: false }
    );

    const refresh = () => {
        getServerResourceUsage(server.uuid).then(setStats).catch(() => setStats(null));
        getServerNodeUptime(server.uuid).then(setNodeUptime).catch(() => setNodeUptime(null));
    };

    useEffect(() => {
        refresh();
        interval.current = setInterval(refresh, 30000);

        return () => interval.current && clearInterval(interval.current);
    }, [server.uuid]);

    const allocation = useMemo(() => {
        const primary = server.allocations.find((item) => item.isDefault);
        return primary ? `${primary.alias || ip(primary.ip)}:${primary.port}` : 'Not assigned';
    }, [server.allocations]);
    const state = stats?.status || status || 'offline';
    const online = state === 'running';
    const stateLabel = state.charAt(0).toUpperCase() + state.slice(1);
    const softwareVersion = server.variables.find((item) => item.envVariable === 'MINECRAFT_VERSION')?.serverValue;
    const software = `${server.eggName}${softwareVersion && softwareVersion !== 'latest' ? ` ${softwareVersion}` : ''}`;
    const memoryLimit = mbToBytes(server.limits.memory);
    const diskLimit = mbToBytes(server.limits.disk);
    const memoryPercent = stats && memoryLimit ? (stats.memoryUsageInBytes / memoryLimit) * 100 : 0;
    const diskPercent = stats && diskLimit ? (stats.diskUsageInBytes / diskLimit) * 100 : 0;

    return (
        <ServerContentBlock title={'Dashboard'} showServerHeader={false}>
            <div className={'fluid-dashboard mx-auto max-w-[1128px]'}>
                <header className={'fluid-dashboard__header'}>
                    <div><h1>{server.name}</h1><p>Dashboard <span>&middot;</span> {software}</p></div>
                    <div className={online ? 'fluid-dashboard__status is-online' : 'fluid-dashboard__status'}><i /> {stateLabel}</div>
                </header>

                <div className={'fluid-dashboard-grid'}>
                    <section className={'fluid-dashboard-card'}>
                        <header><h2>Server details</h2><p>Server identification and details</p></header>
                        <div>
                            <Detail label={'Status'}><span className={online ? 'text-green-400' : undefined}>{stateLabel}</span></Detail>
                            <Detail label={'Address'}>{allocation}</Detail>
                            <Detail label={'Software'}>{software}</Detail>
                            <Detail label={'Uptime'}>{stats && stats.uptime > 0 ? <UptimeDuration uptime={stats.uptime / 1000} /> : 'Offline'}</Detail>
                            <Detail label={'Server ID'}>{server.id}</Detail>
                        </div>
                    </section>

                    <section className={'fluid-dashboard-card'}>
                        <header><h2>Node Details</h2><p>Node specifications and details</p></header>
                        <div>
                            <Detail label={'Node'}>{server.node}</Detail>
                            <Detail label={'Region'}>{server.nodeLocation || 'Not set'}</Detail>
                            <Detail label={'CPU'}>{server.nodeCpuModel || 'Not set'}</Detail>
                            <Detail label={'Memory'}>{server.nodeMemoryType || 'Not set'}</Detail>
                            <Detail label={'Node uptime'}>{nodeUptime === null ? 'Unavailable' : <UptimeDuration uptime={nodeUptime} />}</Detail>
                        </div>
                    </section>

                    <section className={'fluid-dashboard-card fluid-dashboard-activity'}>
                        <header className={'fluid-dashboard-card__header'}>
                            <div><h2>Recent activity</h2><p>Latest changes to this server</p></div>
                            <Link to={`/server/${server.id}/activity`}>View activity <span>&rarr;</span></Link>
                        </header>
                        {!activity && isActivityLoading ? <p className={'fluid-dashboard-empty'}>Loading recent activity…</p> : !activity?.items.length ? <p className={'fluid-dashboard-empty'}>No activity recorded for this server yet.</p> : (
                            <div>{activity.items.slice(0, 3).map((item) => {
                                const actor = item.relationships.actor;
                                return <div className={'fluid-dashboard-activity__item'} key={item.id}>
                                    <i />
                                    <div><strong>{activityTitle(item.event)}</strong><p>{item.description || `Performed by ${actor?.username || 'System'}`}</p></div>
                                    <time>{formatDistanceToNowStrict(item.timestamp, { addSuffix: true })}</time>
                                </div>;
                            })}</div>
                        )}
                    </section>

                    <section className={'fluid-dashboard-card'}>
                        <header><h2>Resource usage</h2><p>Resource utilization</p></header>
                        <div className={'fluid-dashboard-usages'}>
                            <Usage label={'CPU'} value={stats ? `${stats.cpuUsagePercent.toFixed(2)}% of ${server.limits.cpu || '∞'}%` : '—'} percent={server.limits.cpu && stats ? (stats.cpuUsagePercent / server.limits.cpu) * 100 : 0} />
                            <Usage label={'Memory'} value={stats ? `${bytesToString(stats.memoryUsageInBytes)} / ${bytesToString(memoryLimit)}` : '—'} percent={memoryPercent} />
                            <Usage label={'Disk'} value={stats ? `${bytesToString(stats.diskUsageInBytes)} / ${bytesToString(diskLimit)}` : '—'} percent={diskPercent} />
                        </div>
                    </section>
                </div>

                <section className={'fluid-quick-access'}>
                    <header><h2>Quick access</h2><p>Jump directly to common server tasks</p></header>
                    <div>
                        {[['Console', 'View live output and run commands', 'console'], ['Files', 'Browse, edit, upload, and download files', 'files'], ['Backups', 'Create and restore server backups', 'backups'], ['Network', 'Manage allocations and server addresses', 'network']].map(([label, description, path]) => (
                            <Link key={path} to={`/server/${server.id}/${path}`}><strong>{label}</strong><p>{description}</p><span>Open →</span></Link>
                        ))}
                    </div>
                </section>
            </div>
        </ServerContentBlock>
    );
};

export default () => {
    // A direct navigation can render this route while ServerRouter is still
    // fetching its record. Do not dereference the optional store value yet.
    const server = ServerContext.useStoreState((state) => state.server.data);

    return server ? <ServerDashboard server={server} /> : <Spinner centered size={'large'} />;
};
