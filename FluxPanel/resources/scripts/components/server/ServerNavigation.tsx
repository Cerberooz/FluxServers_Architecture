import * as React from 'react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
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
import routes from '@/routers/routes';
import { usePersistedState } from '@/plugins/usePersistedState';
import { useStoreState } from 'easy-peasy';
import { ApplicationStore } from '@/state';
import { ServerContext } from '@/state/server';
import styled from 'styled-components/macro';
import http from '@/api/http';

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
    position: relative;
    isolation: isolate;
    scrollbar-width: none;
    -ms-overflow-style: none;

    &::before,
    &::after {
        position: absolute;
        z-index: 0;
        content: '';
        pointer-events: none;
        opacity: var(--fluid-active-visible, 0);
        transition: top 420ms cubic-bezier(.34, 1.56, .64, 1), height 420ms cubic-bezier(.34, 1.56, .64, 1), opacity 160ms ease;
    }

    &::before {
        top: var(--fluid-active-top, 0px);
        right: 4px;
        left: -4px;
        height: var(--fluid-active-height, 0px);
        border-radius: 8px;
        background: #0a0e15;
    }

    &::after {
        top: calc(var(--fluid-active-top, 0px) - 4px);
        left: -16px;
        width: 5px;
        height: calc(var(--fluid-active-height, 0px) + 8px);
        border-radius: 0 4px 4px 0;
        background: #2582ff;
    }

    &::-webkit-scrollbar {
        display: none;
    }

    a.fluid-server-nav-link-active {
        color: #e8f0ff;
        font-weight: 600;
        background: #101824;
    }
`;

export default ({ baseUrl, serverName, serverMeta, serverId, rootAdmin }: Props) => {
    const panelName = useStoreState((state: ApplicationStore) => state.settings.data!.name);
    const serverUuid = ServerContext.useStoreState((state) => state.server.data?.uuid);
    const [collapsed, setCollapsed] = usePersistedState('layout:server-sidebar:collapsed', false);
    const [mobileOpen, setMobileOpen] = useState(false);
    const location = useLocation();
    const [toolsOpen, setToolsOpen] = useState(() => ['/subdomains', '/optimizer', '/plugins'].some((path) => location.pathname.endsWith(path)));
    const navigationRef = useRef<HTMLElement>(null);
    const [activeIndicator, setActiveIndicator] = useState({ top: 0, height: 0, visible: false });
    const [optimizerUnread, setOptimizerUnread] = useState(0);
    const isCollapsed = !!collapsed;
    const to = (path: string) => (path === '/' ? baseUrl : `${baseUrl.replace(/\/*$/, '')}/${path.replace(/^\/+/, '')}`);
    const toolRoutes = routes.server.filter((route) => ['Subdomains', 'Optimizer', 'Plugins'].includes(route.name || ''));
    const navigationRoutes = routes.server.filter((route) => !!route.name && !toolRoutes.includes(route));

    useEffect(() => {
        if (!serverUuid) {
            setOptimizerUnread(0);

            return;
        }

        let mounted = true;
        http.get(`/api/client/servers/${serverUuid}/optimizer/notifications`)
            .then(({ data }) => mounted && setOptimizerUnread(data.data?.unread || 0))
            .catch(() => mounted && setOptimizerUnread(0));

        return () => { mounted = false; };
    }, [serverUuid, location.pathname]);

    useLayoutEffect(() => {
        const navigation = navigationRef.current;
        if (!navigation) return;

        const updateIndicator = () => {
            const active = navigation.querySelector<HTMLAnchorElement>('a.fluid-server-nav-link-active');
            if (!active) {
                setActiveIndicator((current) => ({ ...current, visible: false }));
                return;
            }

            setActiveIndicator({ top: active.offsetTop + 4, height: Math.max(active.offsetHeight - 8, 0), visible: true });
        };

        const frame = requestAnimationFrame(updateIndicator);
        const observer = new ResizeObserver(updateIndicator);
        observer.observe(navigation);

        return () => {
            cancelAnimationFrame(frame);
            observer.disconnect();
        };
    }, [location.pathname, toolsOpen, isCollapsed]);

    const routeLink = (route: (typeof routes.server)[number], nested = false) => {
        const link = (
            <NavLink
                to={to(route.path)}
                exact={route.exact}
                onClick={() => setMobileOpen(false)}
                className={`relative z-10 flex h-11 shrink-0 items-center rounded-lg border border-transparent px-3 text-neutral-300 no-underline transition-colors duration-200 hover:text-neutral-100 ${nested && !isCollapsed ? 'ml-3' : ''}`}
                activeClassName={'fluid-server-nav-link-active'}
            >
                <FontAwesomeIcon icon={icons[route.name!] || faTerminal} />
                {!isCollapsed && <span className={'ml-3 flex-1 whitespace-nowrap text-sm font-medium'}>{route.name}</span>}
                {route.name === 'Optimizer' && optimizerUnread > 0 && <span className={'ml-2 h-2 w-2 shrink-0 rounded-full bg-red-500'} aria-label={`${optimizerUnread} unread optimizer alert${optimizerUnread === 1 ? '' : 's'}`} />}
            </NavLink>
        );

        return route.permission ? <Can key={route.path} action={route.permission} matchAny>{link}</Can> : <React.Fragment key={route.path}>{link}</React.Fragment>;
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

                    <ScrollNavigation
                        ref={navigationRef}
                        style={{
                            '--fluid-active-top': `${activeIndicator.top}px`,
                            '--fluid-active-height': `${activeIndicator.height}px`,
                            '--fluid-active-visible': activeIndicator.visible ? 1 : 0,
                        } as React.CSSProperties}
                        className={'mt-4 flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1'}
                        aria-label={'Server management'}
                    >
                        {navigationRoutes.map((route) => routeLink(route))}
                        <Can action={['allocation.read', 'file.read-content', 'file.read']} matchAny>
                            <div className={'relative z-10 shrink-0'}>
                                <button
                                    type={'button'}
                                    onClick={() => setToolsOpen((open) => !open)}
                                    className={'flex h-11 w-full items-center rounded-xl border border-transparent px-3 text-neutral-300 transition-all hover:border-neutral-600 hover:bg-neutral-800 hover:text-neutral-100'}
                                    aria-expanded={toolsOpen}
                                >
                                    <FontAwesomeIcon icon={faTools} />
                                    {!isCollapsed && <><span className={'ml-3 flex-1 text-left whitespace-nowrap text-sm font-medium'}>Tools</span>{optimizerUnread > 0 && <span className={'mr-2 h-2 w-2 shrink-0 rounded-full bg-red-500'} aria-label={`${optimizerUnread} unread optimizer alert${optimizerUnread === 1 ? '' : 's'}`} />}<FontAwesomeIcon icon={faChevronDown} className={toolsOpen ? 'transition-transform' : '-rotate-90 transition-transform'} /></>}
                                    {isCollapsed && optimizerUnread > 0 && <span className={'absolute right-2 top-2 h-2 w-2 rounded-full bg-red-500'} />}
                                </button>
                                {toolsOpen && <div className={'mt-1 flex flex-col gap-1'}>{toolRoutes.map((route) => routeLink(route, true))}</div>}
                            </div>
                        </Can>
                    </ScrollNavigation>

                    <div className={'mt-3 shrink-0 border-t border-neutral-700 pt-3'}>
                        {rootAdmin && (
                            <div>
                                <a
                                    href={`/admin/servers/view/${serverId}`}
                                    target={'_blank'}
                                    rel={'noreferrer'}
                                    className={'flex h-11 items-center rounded-xl border border-transparent px-3 text-neutral-300 no-underline transition-all hover:border-neutral-600 hover:bg-neutral-800 hover:text-neutral-100'}
                                >
                                    <FontAwesomeIcon icon={faExternalLinkAlt} />
                                    {!isCollapsed && <span className={'ml-3 whitespace-nowrap text-sm font-medium'}>Admin view</span>}
                                </a>
                            </div>
                        )}
                        <Link
                            to={'/'}
                            onClick={() => setMobileOpen(false)}
                            className={'flex h-11 items-center rounded-xl border border-transparent px-3 text-neutral-300 no-underline transition-all hover:border-neutral-600 hover:bg-neutral-800 hover:text-neutral-100'}
                        >
                            <FontAwesomeIcon icon={faAngleDoubleLeft} />
                            {!isCollapsed && <span className={'ml-3 whitespace-nowrap text-sm font-medium'}>All servers</span>}
                        </Link>
                    </div>
                </div>
            </aside>
            <div className={`hidden shrink-0 transition-[width] duration-200 lg:block ${isCollapsed ? 'w-20' : 'w-56'}`} />
        </>
    );
};
