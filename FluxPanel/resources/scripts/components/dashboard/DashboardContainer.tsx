import React, { useEffect, useState } from 'react';
import { Server } from '@/api/server/getServer';
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

export default () => {
    const { search } = useLocation();
    const defaultPage = Number(new URLSearchParams(search).get('page') || '1');

    const [page, setPage] = useState(!isNaN(defaultPage) && defaultPage > 0 ? defaultPage : 1);
    const { clearFlashes, clearAndAddHttpError } = useFlash();
    const uuid = useStoreState((state) => state.user.data!.uuid);
    const rootAdmin = useStoreState((state) => state.user.data!.rootAdmin);
    const [showOnlyAdmin, setShowOnlyAdmin] = usePersistedState(`${uuid}:show_all_servers`, false);

    const { data: servers, error } = useSWR<PaginatedResult<Server>>(
        ['/api/client/servers', showOnlyAdmin && rootAdmin, page],
        () => getServers({ page, type: showOnlyAdmin && rootAdmin ? 'admin' : undefined })
    );

    useEffect(() => {
        setPage(1);
    }, [showOnlyAdmin]);

    useEffect(() => {
        if (!servers) return;
        if (servers.pagination.currentPage > 1 && !servers.items.length) {
            setPage(1);
        }
    }, [servers?.pagination.currentPage]);

    useEffect(() => {
        // Don't use react-router to handle changing this part of the URL, otherwise it
        // triggers a needless re-render. We just want to track this in the URL incase the
        // user refreshes the page.
        window.history.replaceState(null, document.title, `/${page <= 1 ? '' : `?page=${page}`}`);
    }, [page]);

    useEffect(() => {
        if (error) clearAndAddHttpError({ key: 'dashboard', error });
        if (!error) clearFlashes('dashboard');
    }, [error]);

    const activeServers = servers?.items.filter((server) => server.status !== 'suspended').length || 0;

    return (
        <PageContentBlock title={'Servers'} showFlashKey={'dashboard'}>
            <div css={tw`mb-8 flex items-end justify-between`}>
                <div>
                    <h1 css={tw`text-3xl font-semibold text-neutral-100`}>Servers</h1>
                    <p css={tw`mt-2 text-sm text-neutral-400`}>Manage and monitor your game servers.</p>
                </div>
            </div>
            {servers && (
                <div css={tw`mb-8 grid grid-cols-1 gap-4 md:grid-cols-3`}>
                    <div css={tw`rounded-xl border border-neutral-700 bg-neutral-800 p-5`}><p css={tw`text-xs uppercase tracking-wider text-neutral-400`}>Your servers</p><p css={tw`mt-3 text-2xl font-semibold text-neutral-100`}>{servers.pagination.total}</p></div>
                    <div css={tw`rounded-xl border border-neutral-700 bg-neutral-800 p-5`}><p css={tw`text-xs uppercase tracking-wider text-neutral-400`}>Active</p><p css={tw`mt-3 text-2xl font-semibold text-green-400`}>{activeServers}</p></div>
                    <div css={tw`rounded-xl border border-neutral-700 bg-neutral-800 p-5`}><p css={tw`text-xs uppercase tracking-wider text-neutral-400`}>Panel status</p><p css={tw`mt-3 text-2xl font-semibold text-blue-400`}>Online</p></div>
                </div>
            )}
            {rootAdmin && (
                <div css={tw`mb-2 flex justify-end items-center`}>
                    <p css={tw`uppercase text-xs text-neutral-400 mr-2`}>
                        {showOnlyAdmin ? "Showing others' servers" : 'Showing your servers'}
                    </p>
                    <Switch
                        name={'show_all_servers'}
                        defaultChecked={showOnlyAdmin}
                        onChange={() => setShowOnlyAdmin((s) => !s)}
                    />
                </div>
            )}
            {!servers ? (
                <Spinner centered size={'large'} />
            ) : (
                <Pagination data={servers} onPageSelect={setPage}>
                    {({ items }) =>
                        items.length > 0 ? (
                            items.map((server, index) => (
                                <ServerRow key={server.uuid} server={server} css={index > 0 ? tw`mt-2` : undefined} />
                            ))
                        ) : (
                            <p css={tw`text-center text-sm text-neutral-400`}>
                                {showOnlyAdmin
                                    ? 'There are no other servers to display.'
                                    : 'There are no servers associated with your account.'}
                            </p>
                        )
                    }
                </Pagination>
            )}
        </PageContentBlock>
    );
};
