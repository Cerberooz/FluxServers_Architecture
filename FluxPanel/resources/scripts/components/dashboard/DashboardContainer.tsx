import React, { useEffect, useState } from 'react';
import getServers from '@/api/getServers';
import getDashboardStats, { DashboardStats } from '@/api/getDashboardStats';
import ServerRow from '@/components/dashboard/ServerRow';
import Spinner from '@/components/elements/Spinner';
import PageContentBlock from '@/components/elements/PageContentBlock';
import useFlash from '@/plugins/useFlash';
import { useStoreState } from 'easy-peasy';
import { usePersistedState } from '@/plugins/usePersistedState';
import Switch from '@/components/elements/Switch';
import tw from 'twin.macro';
import useSWR from 'swr';
import { PaginatedResult } from '@/api/http';
import Pagination from '@/components/elements/Pagination';
import { useLocation } from 'react-router-dom';
import { Server } from '@/api/server/getServer';

const formatUptime = (milliseconds: number | null) => {
    if (milliseconds === null) return '—';
    const seconds = Math.floor(milliseconds / 1000);
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return days > 0 ? `${days}d ${hours}h` : (hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`);
};

export default () => {
    const { search } = useLocation();
    const defaultPage = Number(new URLSearchParams(search).get('page') || '1');
    const [page, setPage] = useState(!isNaN(defaultPage) && defaultPage > 0 ? defaultPage : 1);
    const { clearFlashes, clearAndAddHttpError } = useFlash();
    const uuid = useStoreState((state) => state.user.data!.uuid);
    const rootAdmin = useStoreState((state) => state.user.data!.rootAdmin);
    const [showOnlyAdmin, setShowOnlyAdmin] = usePersistedState(`${uuid}:show_all_servers`, false);
    const scope = showOnlyAdmin && rootAdmin ? 'admin-all' : undefined;
    const { data: servers, error } = useSWR<PaginatedResult<Server>>(['/api/client/servers', scope, page], () => getServers({ page, type: scope }));
    const { data: stats } = useSWR<DashboardStats>(['/api/client/dashboard/stats', scope], () => getDashboardStats(scope), { refreshInterval: 30000 });

    useEffect(() => setPage(1), [showOnlyAdmin]);
    useEffect(() => { if (servers && servers.pagination.currentPage > 1 && !servers.items.length) setPage(1); }, [servers?.pagination.currentPage]);
    useEffect(() => { window.history.replaceState(null, document.title, `/${page <= 1 ? '' : `?page=${page}`}`); }, [page]);
    useEffect(() => { if (error) clearAndAddHttpError({ key: 'dashboard', error }); else clearFlashes('dashboard'); }, [error]);

    return (
        <PageContentBlock title={'Servers'} showFlashKey={'dashboard'}>
            <div css={tw`mx-auto max-w-[1180px]`}>
                <header css={tw`flex h-[66px] items-center justify-between`}>
                    <h1 css={tw`text-[27px] font-semibold text-neutral-100`}>Servers</h1>
                    {rootAdmin && <div css={tw`flex items-center`}><span css={tw`mr-2 text-[10px] uppercase text-neutral-500`}>{showOnlyAdmin ? 'Showing all servers' : 'Showing owned and shared servers'}</span><Switch name={'show_all_servers'} defaultChecked={showOnlyAdmin} onChange={() => setShowOnlyAdmin((value) => !value)} /></div>}
                </header>
                <section css={tw`grid min-h-[90px] grid-cols-1 border-b border-t border-neutral-700 sm:grid-cols-3`}>
                    <div css={tw`border-b border-neutral-700 px-[22px] py-[18px] sm:border-b-0 sm:border-r`}><p css={tw`text-xl font-semibold text-neutral-100`}><span css={tw`mr-2 inline-block h-2 w-2 rounded-full bg-green-400`} />{stats ? `${stats.online} / ${stats.total}` : '—'}</p><p css={tw`mt-1 text-[9px] font-medium uppercase tracking-wider text-neutral-400`}>Servers online</p><p css={tw`mt-1 text-[9px] text-neutral-600`}>{stats ? `${stats.offline} server${stats.offline === 1 ? '' : 's'} currently offline` : 'Loading server status'}</p></div>
                    <div css={tw`border-b border-neutral-700 px-[22px] py-[18px] sm:border-b-0 sm:border-r`}><p css={tw`text-xl font-semibold text-neutral-100`}>{stats?.playersOnline ?? '—'}</p><p css={tw`mt-1 text-[9px] font-medium uppercase tracking-wider text-neutral-400`}>Players online</p><p css={tw`mt-1 text-[9px] text-neutral-600`}>{stats ? (stats.playersQueried ? `Live count from ${stats.playersQueried} online server${stats.playersQueried === 1 ? '' : 's'}` : 'No online Minecraft servers could be queried') : 'Loading live player count'}</p></div>
                    <div css={tw`px-[22px] py-[18px]`}><p css={tw`text-xl font-semibold text-neutral-100`}>{stats ? formatUptime(stats.averageUptime) : '—'}</p><p css={tw`mt-1 text-[9px] font-medium uppercase tracking-wider text-neutral-400`}>Server uptime</p><p css={tw`mt-1 text-[9px] text-neutral-600`}>{stats ? `Average across ${stats.total} selected server${stats.total === 1 ? '' : 's'}` : 'Loading average uptime'}</p></div>
                </section>
                <div css={tw`flex h-[58px] items-center`}><h2 css={tw`text-sm font-semibold text-neutral-100`}>Your servers</h2></div>
                {!servers ? <Spinner centered size={'large'} /> : <Pagination data={servers} onPageSelect={setPage}>{({ items }) => items.length > 0 ? <div css={tw`overflow-x-auto`}><div css={tw`grid w-[1180px] border-b border-neutral-700 pb-2 text-[9px] font-medium uppercase tracking-wider text-neutral-400`} style={{ gridTemplateColumns: '340px 150px 140px 100px 160px 160px 130px' }}><span>Server</span><span>Region</span><span>Status</span><span>CPU</span><span>Memory</span><span>Disk</span><span /></div>{items.map((server) => <ServerRow key={server.uuid} server={server} />)}</div> : <p css={tw`py-8 text-center text-sm text-neutral-500`}>{showOnlyAdmin ? 'There are no servers to display.' : 'There are no servers associated with your account.'}</p>}</Pagination>}
            </div>
        </PageContentBlock>
    );
};
