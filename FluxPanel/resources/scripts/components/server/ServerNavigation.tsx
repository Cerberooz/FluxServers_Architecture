import * as React from 'react';
import { useState } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
    faAngleDoubleLeft,
    faArchive,
    faBars,
    faCalendarAlt,
    faChevronDown,
    faCog,
    faDatabase,
    faExternalLinkAlt,
    faFolderOpen,
    faHistory,
    faLayerGroup,
    faNetworkWired,
    faRocket,
    faTerminal,
    faTimes,
    faTools,
    faUsers,
} from '@fortawesome/free-solid-svg-icons';
import { IconDefinition } from '@fortawesome/fontawesome-svg-core';
import Can from '@/components/elements/Can';
import Tooltip from '@/components/elements/tooltip/Tooltip';
import routes from '@/routers/routes';
import { usePersistedState } from '@/plugins/usePersistedState';
import { useStoreState } from 'easy-peasy';
import { ApplicationStore } from '@/state';
import styled from 'styled-components/macro';

type Props = {
    baseUrl: string;
    serverName: string;
    serverMeta: string;
    serverId: number;
    rootAdmin: boolean;
};

const icons: Record<string, IconDefinition> = {
    Dashboard: faLayerGroup,
    Console: faTerminal,
    Files: faFolderOpen,
    Databases: faDatabase,
    Schedules: faCalendarAlt,
    Users: faUsers,
    Backups: faArchive,
    Network: faNetworkWired,
    Startup: faRocket,
    Subdomains: faNetworkWired,
    Optimizer: faRocket,
    Plugins: faLayerGroup,
    Settings: faCog,
    Activity: faHistory,
};

const ScrollNavigation = styled.nav`
    scrollbar-width: none;
    -ms-overflow-style: none;

    &::-webkit-scrollbar {
        display: none;
    }
`;

export default ({ baseUrl, serverName, serverMeta, serverId, rootAdmin }: Props) => {
    const panelName = useStoreState((state: ApplicationStore) => state.settings.data!.name);
    const [collapsed, setCollapsed] = usePersistedState('layout:server-sidebar:collapsed', false);
    const [mobileOpen, setMobileOpen] = useState(false);
    const location = useLocation();
    const [toolsOpen, setToolsOpen] = useState(() => ['/subdomains', '/optimizer', '/plugins'].some((path) => location.pathname.endsWith(path)));
    const isCollapsed = !!collapsed;
    const to = (path: string) => (path === '/' ? baseUrl : `${baseUrl.replace(/\/*$/, '')}/${path.replace(/^\/+/, '')}`);
    const toolRoutes = routes.server.filter((route) => ['Subdomains', 'Optimizer', 'Plugins'].includes(route.name || ''));
    const navigationRoutes = routes.server.filter((route) => !!route.name && !toolRoutes.includes(route));

    const routeLink = (route: (typeof routes.server)[number], nested = false) => {
        const link = (
            <NavLink
                to={to(route.path)}
                exact={route.exact}
                onClick={() => setMobileOpen(false)}
                className={`flex h-11 items-center rounded-lg border border-transparent px-3 text-neutral-300 no-underline transition-all hover:bg-neutral-800 hover:text-neutral-100 ${nested && !isCollapsed ? 'ml-3' : ''}`}
                activeClassName={'border-l-2 border-primary-500 bg-neutral-800 text-neutral-100 rounded-l-none'}
            >
                <FontAwesomeIcon icon={icons[route.name!] || faTerminal} />
                {!isCollapsed && <span className={'ml-3 whitespace-nowrap text-sm font-medium'}>{route.name}</span>}
            </NavLink>
        );

        const wrapped = <Tooltip placement={isCollapsed ? 'right' : 'bottom'} content={route.name!}>{link}</Tooltip>;
        return route.permission ? <Can key={route.path} action={route.permission} matchAny>{wrapped}</Can> : <React.Fragment key={route.path}>{wrapped}</React.Fragment>;
    };

    return (
        <>
            <button
                type={'button'}
                aria-label={'Open server navigation'}
                onClick={() => setMobileOpen(true)}
                className={'fixed left-4 top-4 z-40 flex h-11 w-11 items-center justify-center rounded-xl border border-neutral-600 bg-neutral-900 text-neutral-200 shadow-lg lg:hidden'}
            >
                <FontAwesomeIcon icon={faBars} />
            </button>
            {mobileOpen && (
                <button
                    type={'button'}
                    aria-label={'Close server navigation'}
                    onClick={() => setMobileOpen(false)}
                    className={'fixed inset-0 z-30 bg-black/50 lg:hidden'}
                />
            )}
            <aside
                className={`fixed inset-y-0 left-0 z-40 flex overflow-hidden border-r border-neutral-600 bg-neutral-900 shadow-2xl transition-[width,transform] duration-200 lg:translate-x-0 ${
                    isCollapsed ? 'w-20' : 'w-56'
                } ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}`}
            >
                <div className={'flex h-full w-full min-w-0 flex-col p-4'}>
                    <div className={`flex min-w-0 items-center ${isCollapsed ? 'justify-center' : 'justify-between'}`}>
                        {!isCollapsed && (
                            <div className={'min-w-0'}>
                                <Link
                                    to={'/'}
                                    className={'inline-flex items-center gap-3 text-xl font-header font-semibold text-neutral-100 no-underline hover:text-white'}
                                    title={'Back to dashboard'}
                                >
                                    <img
                                        src={'/favicons/flux_logo.jpg'}
                                        alt={panelName}
                                        className={'h-10 w-10 shrink-0 rounded-xl border border-neutral-600 object-cover'}
                                    />
                                    <span className={'truncate'}>{panelName}</span>
                                </Link>
                            </div>
                        )}
                        <button
                            type={'button'}
                            aria-label={isCollapsed ? 'Expand server navigation' : 'Collapse server navigation'}
                            onClick={() => setCollapsed((value) => !value)}
                            className={'hidden h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-neutral-600 bg-neutral-900 text-neutral-300 transition-colors hover:bg-neutral-800 hover:text-neutral-100 lg:flex'}
                        >
                            <FontAwesomeIcon icon={faAngleDoubleLeft} className={isCollapsed ? 'rotate-180 transition-transform' : 'transition-transform'} />
                        </button>
                        <button
                            type={'button'}
                            aria-label={'Close server navigation'}
                            onClick={() => setMobileOpen(false)}
                            className={'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-neutral-600 bg-neutral-900 text-neutral-300 lg:hidden'}
                        >
                            <FontAwesomeIcon icon={faTimes} />
                        </button>
                    </div>

                    {!isCollapsed && (
                        <div className={'mt-6 min-w-0 px-3'}>
                            <p className={'truncate text-sm font-semibold text-neutral-100'}>{serverName}</p>
                            {serverMeta && <p className={'mt-1 truncate text-[10px] text-neutral-400'}>{serverMeta}</p>}
                        </div>
                    )}

                    <ScrollNavigation className={'mt-4 flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1'} aria-label={'Server management'}>
                        {navigationRoutes.map((route) => routeLink(route))}
                        <Can action={['allocation.read', 'file.read-content', 'file.read']} matchAny>
                            <div>
                                <Tooltip placement={isCollapsed ? 'right' : 'bottom'} content={'Tools'}>
                                    <button
                                        type={'button'}
                                        onClick={() => setToolsOpen((open) => !open)}
                                        className={'flex h-11 w-full items-center rounded-xl border border-transparent px-3 text-neutral-300 transition-all hover:border-neutral-600 hover:bg-neutral-800 hover:text-neutral-100'}
                                        aria-expanded={toolsOpen}
                                    >
                                        <FontAwesomeIcon icon={faTools} />
                                        {!isCollapsed && <><span className={'ml-3 flex-1 text-left whitespace-nowrap text-sm font-medium'}>Tools</span><FontAwesomeIcon icon={faChevronDown} className={toolsOpen ? 'transition-transform' : '-rotate-90 transition-transform'} /></>}
                                    </button>
                                </Tooltip>
                                {toolsOpen && <div className={'mt-1 flex flex-col gap-1'}>{toolRoutes.map((route) => routeLink(route, true))}</div>}
                            </div>
                        </Can>
                    </ScrollNavigation>

                    <div className={'mt-3 shrink-0 border-t border-neutral-700 pt-3'}>
                        {rootAdmin && (
                            <div>
                                <Tooltip placement={isCollapsed ? 'right' : 'bottom'} content={'Open admin server view'}>
                                    <a
                                        href={`/admin/servers/view/${serverId}`}
                                        target={'_blank'}
                                        rel={'noreferrer'}
                                        className={'flex h-11 items-center rounded-xl border border-transparent px-3 text-neutral-300 no-underline transition-all hover:border-neutral-600 hover:bg-neutral-800 hover:text-neutral-100'}
                                    >
                                        <FontAwesomeIcon icon={faExternalLinkAlt} />
                                        {!isCollapsed && <span className={'ml-3 whitespace-nowrap text-sm font-medium'}>Admin view</span>}
                                    </a>
                                </Tooltip>
                            </div>
                        )}
                        <Tooltip placement={isCollapsed ? 'right' : 'bottom'} content={'All servers'}>
                            <Link
                                to={'/'}
                                onClick={() => setMobileOpen(false)}
                                className={'flex h-11 items-center rounded-xl border border-transparent px-3 text-neutral-300 no-underline transition-all hover:border-neutral-600 hover:bg-neutral-800 hover:text-neutral-100'}
                            >
                                <FontAwesomeIcon icon={faAngleDoubleLeft} />
                                {!isCollapsed && <span className={'ml-3 whitespace-nowrap text-sm font-medium'}>All servers</span>}
                            </Link>
                        </Tooltip>
                    </div>
                </div>
            </aside>
            <div className={`hidden shrink-0 transition-[width] duration-200 lg:block ${isCollapsed ? 'w-20' : 'w-56'}`} />
        </>
    );
};
