import React, { useEffect, useMemo, useRef, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCircle, faClock, faHdd, faMemory, faMicrochip, faNetworkWired, faServer } from '@fortawesome/free-solid-svg-icons';
import { formatDistanceToNowStrict } from 'date-fns';
import { ServerContext } from '@/state/server';
import ServerContentBlock from '@/components/elements/ServerContentBlock';
import getServerResourceUsage, { ServerStats } from '@/api/server/getServerResourceUsage';
import { useActivityLogs } from '@/api/server/activity';
import { bytesToString, ip, mbToBytes } from '@/lib/formatters';
import UptimeDuration from '@/components/server/UptimeDuration';
import PowerButtons from '@/components/server/console/PowerButtons';
import Can from '@/components/elements/Can';

type Timer = ReturnType<typeof setInterval>;

const Detail = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div className={'grid grid-cols-[136px_minmax(0,1fr)] gap-4 py-3'}>
        <span className={'text-[9px] font-medium uppercase tracking-wider text-neutral-500'}>{label}</span>
        <span className={'truncate text-sm font-medium text-neutral-100'}>{children}</span>
    </div>
);

const Resource = ({ icon, label, value, limit }: { icon: typeof faMicrochip; label: string; value: string; limit: string }) => (
    <div className={'border-b border-neutral-700 py-4 last:border-b-0'}>
        <div className={'flex items-center justify-between'}>
            <span className={'flex items-center gap-2 text-xs font-medium text-neutral-300'}><FontAwesomeIcon icon={icon} className={'text-neutral-500'} />{label}</span>
            <span className={'text-xs font-semibold text-neutral-100'}>{value}</span>
        </div>
        <p className={'mt-2 text-[10px] text-neutral-500'}>{limit}</p>
    </div>
);

const activityTitle = (event: string) => event.replace(/[:._-]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());

export default () => {
    const server = ServerContext.useStoreState((state) => state.server.data!);
    const status = ServerContext.useStoreState((state) => state.status.value);
    const [stats, setStats] = useState<ServerStats | null>(null);
    const interval = useRef<Timer>(null) as React.MutableRefObject<Timer>;
    const { data: activity, isValidating: isActivityLoading } = useActivityLogs(
        { page: 1, perPage: 3, sorts: { timestamp: -1 } },
        { revalidateOnMount: true, revalidateOnFocus: false }
    );

    const refresh = () => getServerResourceUsage(server.uuid).then(setStats).catch(() => setStats(null));

    useEffect(() => {
        refresh();
        interval.current = setInterval(refresh, 30000);

        return () => {
            if (interval.current) clearInterval(interval.current);
        };
    }, [server.uuid]);

    const allocation = useMemo(() => {
        const primary = server.allocations.find((item) => item.isDefault);
        return primary ? `${primary.alias || ip(primary.ip)}:${primary.port}` : 'Not assigned';
    }, [server.allocations]);
    const currentState = stats?.status || status || 'offline';
    const online = currentState === 'running';
    const stateLabel = currentState.charAt(0).toUpperCase() + currentState.slice(1);

    return (
        <ServerContentBlock title={'Dashboard'} showServerHeader={false}>
            <div className={'mx-auto max-w-[1128px]'}>
                <header className={'flex min-h-[76px] items-start justify-between border-b border-neutral-700 pt-2'}>
                    <div>
                        <h1 className={'font-header text-2xl font-semibold text-neutral-100'}>{server.name}</h1>
                        <p className={'mt-2 text-xs text-neutral-400'}>Dashboard · {server.eggName}</p>
                    </div>
                    <div className={'flex items-center gap-2 pt-2 text-[10px] font-semibold uppercase tracking-wider'}>
                        <FontAwesomeIcon icon={faCircle} className={online ? 'text-green-400' : 'text-neutral-500'} />
                        <span className={online ? 'text-green-400' : 'text-neutral-400'}>{stateLabel}</span>
                    </div>
                </header>

                <div className={'mt-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(360px,0.85fr)]'}>
                    <section className={'border border-neutral-700 bg-neutral-900'}>
                        <div className={'border-b border-neutral-700 px-5 py-4'}>
                            <h2 className={'text-sm font-semibold text-neutral-100'}>Server details</h2>
                            <p className={'mt-1 text-[10px] text-neutral-400'}>Server identification and connection details</p>
                        </div>
                        <div className={'divide-y divide-neutral-700 px-5'}>
                            <Detail label={'Status'}><span className={online ? 'text-green-400' : 'text-neutral-300'}>{stateLabel}</span></Detail>
                            <Detail label={'Address'}>{allocation}</Detail>
                            <Detail label={'Software'}>{server.eggName}</Detail>
                            <Detail label={'Uptime'}>{stats && stats.uptime > 0 ? <UptimeDuration uptime={stats.uptime / 1000} /> : 'Offline'}</Detail>
                            <Detail label={'Node'}>{server.node}</Detail>
                            {server.nodeCpuModel && <Detail label={'Node CPU'}>{server.nodeCpuModel}</Detail>}
                            {server.nodeMemoryType && <Detail label={'Node memory'}>{server.nodeMemoryType}</Detail>}
                        </div>
                    </section>

                    <section className={'border border-neutral-700 bg-neutral-900'}>
                        <div className={'flex items-start justify-between border-b border-neutral-700 px-5 py-4'}>
                            <div>
                                <h2 className={'text-sm font-semibold text-neutral-100'}>Server controls</h2>
                                <p className={'mt-1 text-[10px] text-neutral-400'}>Manage this server&apos;s power state</p>
                            </div>
                            <FontAwesomeIcon icon={faServer} className={'text-neutral-500'} />
                        </div>
                        <Can action={['control.start', 'control.stop', 'control.restart']} matchAny>
                            <PowerButtons className={'flex gap-2 px-5 py-5'} />
                        </Can>
                    </section>
                </div>

                <section className={'mt-5 border border-neutral-700 bg-neutral-900'}>
                    <div className={'border-b border-neutral-700 px-5 py-4'}>
                        <h2 className={'text-sm font-semibold text-neutral-100'}>Live resources</h2>
                        <p className={'mt-1 text-[10px] text-neutral-400'}>Current server usage</p>
                    </div>
                    <div className={'grid divide-y divide-neutral-700 px-5 md:grid-cols-3 md:divide-x md:divide-y-0'}>
                        <div className={'md:pr-5'}><Resource icon={faMicrochip} label={'CPU'} value={stats ? `${stats.cpuUsagePercent.toFixed(2)}%` : '—'} limit={server.limits.cpu ? `${server.limits.cpu}% limit` : 'Unlimited'} /></div>
                        <div className={'md:px-5'}><Resource icon={faMemory} label={'Memory'} value={stats ? bytesToString(stats.memoryUsageInBytes) : '—'} limit={`${bytesToString(mbToBytes(server.limits.memory))} limit`} /></div>
                        <div className={'md:pl-5'}><Resource icon={faHdd} label={'Disk'} value={stats ? bytesToString(stats.diskUsageInBytes) : '—'} limit={`${bytesToString(mbToBytes(server.limits.disk))} limit`} /></div>
                    </div>
                </section>

                <section className={'mt-5 border border-neutral-700 bg-neutral-900'}>
                    <div className={'border-b border-neutral-700 px-5 py-4'}>
                        <h2 className={'text-sm font-semibold text-neutral-100'}>Recent activity</h2>
                        <p className={'mt-1 text-[10px] text-neutral-400'}>Latest changes to this server</p>
                    </div>
                    <div className={'px-5'}>
                        {!activity && isActivityLoading ? (
                            <p className={'py-7 text-center text-xs text-neutral-500'}>Loading recent activity…</p>
                        ) : !activity?.items.length ? (
                            <p className={'py-7 text-center text-xs text-neutral-500'}>No activity recorded for this server yet.</p>
                        ) : activity.items.map((item) => {
                            const actor = item.relationships.actor;

                            return (
                                <div key={item.id} className={'flex gap-3 border-b border-neutral-700 py-4 last:border-b-0'}>
                                    <span className={'mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-cyan-400'} />
                                    <div className={'min-w-0 flex-1'}>
                                        <div className={'flex items-baseline justify-between gap-3'}>
                                            <p className={'truncate text-xs font-medium text-neutral-100'}>{activityTitle(item.event)}</p>
                                            <span className={'whitespace-nowrap text-[10px] text-neutral-500'}>{formatDistanceToNowStrict(item.timestamp, { addSuffix: true })}</span>
                                        </div>
                                        <p className={'mt-1 truncate text-[11px] text-neutral-400'}>{item.description || `Performed by ${actor?.username || 'System'}`}</p>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </section>

                <section className={'mt-5 border border-neutral-700 bg-neutral-900 px-5 py-4'}>
                    <div className={'flex items-center gap-2'}><FontAwesomeIcon icon={faNetworkWired} className={'text-neutral-500'} /><h2 className={'text-sm font-semibold text-neutral-100'}>Network activity</h2></div>
                    <p className={'mt-3 text-xs text-neutral-400'}>{stats ? `${bytesToString(stats.networkRxInBytes)} inbound · ${bytesToString(stats.networkTxInBytes)} outbound` : 'Live network data will appear when Wings is connected.'}</p>
                </section>
            </div>
        </ServerContentBlock>
    );
};
