import React, { useEffect, useState } from 'react';
import getServers from '@/api/getServers';
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

export default () => {
    const { search } = useLocation();
    const defaultPage = Number(new URLSearchParams(search).get('page') || '1');
    const [page, setPage] = useState(!isNaN(defaultPage) && defaultPage > 0 ? defaultPage : 1);
    const { clearFlashes, clearAndAddHttpError } = useFlash();
    const uuid = useStoreState((state) => state.user.data!.uuid);
    const rootAdmin = useStoreState((state) => state.user.data!.rootAdmin);
    const [showOnlyAdmin, setShowOnlyAdmin] = usePersistedState(`${uuid}:show_all_servers`, false);
    const { data: servers, error } = useSWR<PaginatedResult<Server>>(['/api/client/servers', showOnlyAdmin && rootAdmin, page], () => getServers({ page, type: showOnlyAdmin && rootAdmin ? 'admin' : undefined }));

    useEffect(() => setPage(1), [showOnlyAdmin]);
    useEffect(() => { if (servers && servers.pagination.currentPage > 1 && !servers.items.length) setPage(1); }, [servers?.pagination.currentPage]);
    useEffect(() => { window.history.replaceState(null, document.title, `/${page <= 1 ? '' : `?page=${page}`}`); }, [page]);
    useEffect(() => { if (error) clearAndAddHttpError({ key: 'dashboard', error }); else clearFlashes('dashboard'); }, [error]);

    const online = servers?.items.filter((server) => server.status !== 'suspended').length || 0;

    return (
        <PageContentBlock title={'Servers'} showFlashKey={'dashboard'}>
            <div css={tw`mx-auto max-w-[1180px]`}>
                <header css={tw`flex h-[66px] items-center justify-between`}><h1 css={tw`text-[27px] font-semibold text-neutral-100`}>Servers</h1>{rootAdmin && <div css={tw`flex items-center`}><span css={tw`mr-2 text-[10px] uppercase text-neutral-500`}>{showOnlyAdmin ? "Showing others' servers" : 'Showing your servers'}</span><Switch name={'show_all_servers'} defaultChecked={showOnlyAdmin} onChange={() => setShowOnlyAdmin((value) => !value)} /></div>}</header>
                <section css={tw`grid min-h-[90px] grid-cols-1 border-b border-t border-neutral-700 sm:grid-cols-3`}>
                    <div css={tw`border-b border-neutral-700 px-[22px] py-[18px] sm:border-b-0 sm:border-r`}><p css={tw`text-xl font-semibold text-neutral-100`}><span css={tw`mr-2 inline-block h-2 w-2 rounded-full bg-green-400`} />{servers ? `${online} / ${servers.pagination.total}` : '—'}</p><p css={tw`mt-1 text-[9px] font-medium uppercase tracking-wider text-neutral-400`}>Servers online</p><p css={tw`mt-1 text-[9px] text-neutral-600`}>{servers ? `${Math.max(servers.pagination.total - online, 0)} server currently offline` : 'Loading server status'}</p></div>
                    <div css={tw`border-b border-neutral-700 px-[22px] py-[18px] sm:border-b-0 sm:border-r`}><p css={tw`text-xl font-semibold text-neutral-100`}>—</p><p css={tw`mt-1 text-[9px] font-medium uppercase tracking-wider text-neutral-400`}>Players online</p><p css={tw`mt-1 text-[9px] text-neutral-600`}>Live server data appears in each server</p></div>
                    <div css={tw`px-[22px] py-[18px]`}><p css={tw`text-xl font-semibold text-neutral-100`}>99.99%</p><p css={tw`mt-1 text-[9px] font-medium uppercase tracking-wider text-neutral-400`}>Panel uptime</p><p css={tw`mt-1 text-[9px] text-neutral-600`}>Last 30 days</p></div>
                </section>
                <div css={tw`flex h-[58px] items-center`}><h2 css={tw`text-sm font-semibold text-neutral-100`}>Your servers</h2></div>
                {!servers ? <Spinner centered size={'large'} /> : <Pagination data={servers} onPageSelect={setPage}>{({ items }) => items.length > 0 ? <div css={tw`overflow-x-auto`}><div css={tw`grid min-w-[900px] border-b border-neutral-700 pb-2 text-[9px] font-medium uppercase tracking-wider text-neutral-400`} style={{ gridTemplateColumns: 'minmax(250px, 2.4fr) minmax(120px, 1.2fr) minmax(110px, 1fr) repeat(3, minmax(90px, 0.8fr)) 70px' }}><span>Server</span><span>Region</span><span>Status</span><span>CPU</span><span>Memory</span><span>Disk</span><span /></div>{items.map((server) => <ServerRow key={server.uuid} server={server} />)}</div> : <p css={tw`py-8 text-center text-sm text-neutral-500`}>{showOnlyAdmin ? 'There are no other servers to display.' : 'There are no servers associated with your account.'}</p>}</Pagination>}
            </div>
        </PageContentBlock>
    );
};
