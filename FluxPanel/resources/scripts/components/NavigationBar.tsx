import * as React from 'react';
import { useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faAngleDoubleLeft, faBars, faCogs, faLayerGroup, faSignOutAlt, faTimes } from '@fortawesome/free-solid-svg-icons';
import { useStoreState } from 'easy-peasy';
import { ApplicationStore } from '@/state';
import SearchContainer from '@/components/dashboard/search/SearchContainer';
import tw, { theme } from 'twin.macro';
import styled from 'styled-components/macro';
import http from '@/api/http';
import SpinnerOverlay from '@/components/elements/SpinnerOverlay';
import Tooltip from '@/components/elements/tooltip/Tooltip';
import Avatar from '@/components/Avatar';
import { usePersistedState } from '@/plugins/usePersistedState';

const NavigationGroup = styled.div`
    & > a,
    & > button,
    & > .navigation-link {
        ${tw`flex items-center h-11 w-full no-underline text-neutral-300 px-3 cursor-pointer transition-all duration-150 rounded-xl border border-transparent`};

        &:active,
        &:hover {
            ${tw`text-neutral-100 bg-neutral-800 border-neutral-600`};
        }

        &:active,
        &:hover,
        &.active {
            ${tw`bg-neutral-800 border-neutral-600 text-neutral-100`};
        }
    }
`;

const Label = styled.span<{ $collapsed: boolean }>`
    ${tw`ml-3 text-sm font-medium whitespace-nowrap overflow-hidden transition-all duration-200`};
    width: ${({ $collapsed }) => ($collapsed ? '0' : 'auto')};
    opacity: ${({ $collapsed }) => ($collapsed ? 0 : 1)};
`;

const SidebarButton = styled.button`
    ${tw`flex items-center justify-center h-10 w-10 rounded-xl border border-neutral-600 bg-neutral-900 text-neutral-300 transition-all duration-150`};

    &:hover {
        ${tw`bg-neutral-800 text-neutral-100`};
    }
`;

const SidebarShell = styled.aside<{ $collapsed: boolean; $mobileOpen: boolean }>`
    ${tw`fixed inset-y-0 left-0 z-40 flex overflow-hidden border-r border-neutral-600 bg-neutral-900 shadow-2xl backdrop-blur lg:translate-x-0`};
    width: ${({ $collapsed }) => ($collapsed ? '5rem' : '18rem')};
    transform: translateX(${({ $mobileOpen }) => ($mobileOpen ? '0' : '-100%')});
    transition: width 200ms ease, transform 200ms ease;

    @media (min-width: 1024px) {
        transform: translateX(0);
    }
`;

const RightNavigation = styled.div`
    & > a,
    & > button,
    & > .navigation-link {
        ${tw`flex items-center justify-center h-10 no-underline text-neutral-300 px-3 cursor-pointer transition-all duration-150 rounded-lg border border-transparent`};
        min-width: 2.5rem;

        &:active,
        &:hover {
            ${tw`text-neutral-100 bg-neutral-800 border-neutral-600`};
        }

        &:active,
        &:hover,
        &.active {
            box-shadow: inset 0 -2px ${theme`colors.cyan.500`.toString()};
        }
    }
`;

type Props = {
    sidebar?: boolean;
};

export default ({ sidebar = false }: Props) => {
    const name = useStoreState((state: ApplicationStore) => state.settings.data!.name);
    const rootAdmin = useStoreState((state: ApplicationStore) => state.user.data!.rootAdmin);
    const [isLoggingOut, setIsLoggingOut] = useState(false);
    const [collapsed, setCollapsed] = usePersistedState('layout:sidebar:collapsed', false);
    const [mobileOpen, setMobileOpen] = useState(false);

    const onTriggerLogout = () => {
        setIsLoggingOut(true);
        http.post('/auth/logout').finally(() => {
            // @ts-expect-error this is valid
            window.location = '/';
        });
    };

    const navCollapsed = !!collapsed;

    if (!sidebar) {
        return (
            <div className={'w-full bg-neutral-900 border-b border-neutral-600 shadow-md overflow-x-auto'}>
                <SpinnerOverlay visible={isLoggingOut} />
                <div className={'mx-auto w-full flex items-center h-[4.25rem] max-w-[1280px] px-4 sm:px-6'}>
                    <div id={'logo'} className={'flex-1'}>
                        <Link
                            to={'/'}
                            className={
                                'inline-flex items-center gap-3 text-xl font-header font-semibold no-underline text-neutral-100 hover:text-white transition-colors duration-150'
                            }
                        >
                            <img
                                src={'/favicons/flux_logo.jpg'}
                                alt={'Fluid'}
                                className={'h-9 w-9 rounded-lg border border-neutral-600 object-cover'}
                            />
                            <span>{name}</span>
                        </Link>
                    </div>
                    <RightNavigation className={'flex items-center justify-center gap-2'}>
                        <SearchContainer />
                        <Tooltip placement={'bottom'} content={'Dashboard'}>
                            <NavLink to={'/'} exact>
                                <FontAwesomeIcon icon={faLayerGroup} />
                            </NavLink>
                        </Tooltip>
                        {rootAdmin && (
                            <Tooltip placement={'bottom'} content={'Admin'}>
                                <a href={'/admin'} rel={'noreferrer'}>
                                    <FontAwesomeIcon icon={faCogs} />
                                </a>
                            </Tooltip>
                        )}
                        <Tooltip placement={'bottom'} content={'Account Settings'}>
                            <NavLink to={'/account'}>
                                <span className={'flex items-center w-5 h-5'}>
                                    <Avatar.User />
                                </span>
                            </NavLink>
                        </Tooltip>
                        <Tooltip placement={'bottom'} content={'Sign Out'}>
                            <button onClick={onTriggerLogout}>
                                <FontAwesomeIcon icon={faSignOutAlt} />
                            </button>
                        </Tooltip>
                    </RightNavigation>
                </div>
            </div>
        );
    }

    return (
        <>
            <SpinnerOverlay visible={isLoggingOut} />
            <button
                type={'button'}
                onClick={() => setMobileOpen(true)}
                className={'fixed left-4 top-4 z-40 flex h-11 w-11 items-center justify-center rounded-xl border border-neutral-600 bg-neutral-900 text-neutral-200 shadow-lg lg:hidden'}
            >
                <FontAwesomeIcon icon={faBars} />
            </button>
            {mobileOpen && (
                <button
                    type={'button'}
                    aria-label={'Close navigation'}
                    onClick={() => setMobileOpen(false)}
                    className={'fixed inset-0 z-30 bg-black/50 lg:hidden'}
                />
            )}
            <SidebarShell $collapsed={navCollapsed} $mobileOpen={mobileOpen}>
                <div className={'flex w-full flex-col p-4'}>
                    <div className={'flex items-center justify-between'}>
                        {!navCollapsed && (
                            <Link
                                to={'/'}
                                onClick={() => setMobileOpen(false)}
                                className={'inline-flex items-center gap-3 overflow-hidden text-xl font-header font-semibold no-underline text-neutral-100 transition-all duration-200'}
                            >
                                <img
                                    src={'/favicons/flux_logo.jpg'}
                                    alt={'Fluid'}
                                    className={'h-10 w-10 shrink-0 rounded-xl border border-neutral-600 object-cover'}
                                />
                                <Label $collapsed={navCollapsed}>{name}</Label>
                            </Link>
                        )}
                        <div className={'flex items-center gap-2'}>
                            <div className={'hidden lg:block'}>
                                <SidebarButton type={'button'} onClick={() => setCollapsed((value) => !value)}>
                                    <FontAwesomeIcon
                                        icon={faAngleDoubleLeft}
                                        className={`transition-transform duration-200 ${navCollapsed ? 'rotate-180' : ''}`}
                                    />
                                </SidebarButton>
                            </div>
                            <div className={'lg:hidden'}>
                                <SidebarButton type={'button'} onClick={() => setMobileOpen(false)}>
                                    <FontAwesomeIcon icon={faTimes} />
                                </SidebarButton>
                            </div>
                        </div>
                    </div>
                    <NavigationGroup className={'mt-6 flex flex-col gap-2'}>
                        <SearchContainer collapsed={navCollapsed} />
                        <Tooltip placement={navCollapsed ? 'right' : 'bottom'} content={'Dashboard'}>
                            <NavLink to={'/'} exact onClick={() => setMobileOpen(false)}>
                                <FontAwesomeIcon icon={faLayerGroup} />
                                <Label $collapsed={navCollapsed}>Dashboard</Label>
                            </NavLink>
                        </Tooltip>
                        {rootAdmin && (
                            <Tooltip placement={navCollapsed ? 'right' : 'bottom'} content={'Admin'}>
                                <a href={'/admin'} rel={'noreferrer'} onClick={() => setMobileOpen(false)}>
                                    <FontAwesomeIcon icon={faCogs} />
                                    <Label $collapsed={navCollapsed}>Admin</Label>
                                </a>
                            </Tooltip>
                        )}
                        <Tooltip placement={navCollapsed ? 'right' : 'bottom'} content={'Account Settings'}>
                            <NavLink to={'/account'} onClick={() => setMobileOpen(false)}>
                                <span className={'flex h-5 w-5 items-center'}>
                                    <Avatar.User size={20} />
                                </span>
                                <Label $collapsed={navCollapsed}>Account</Label>
                            </NavLink>
                        </Tooltip>
                    </NavigationGroup>
                    <div className={'mt-auto'}>
                        <NavigationGroup className={'flex flex-col gap-2'}>
                            <Tooltip placement={navCollapsed ? 'right' : 'bottom'} content={'Sign Out'}>
                                <button onClick={onTriggerLogout}>
                                    <FontAwesomeIcon icon={faSignOutAlt} />
                                    <Label $collapsed={navCollapsed}>Sign Out</Label>
                                </button>
                            </Tooltip>
                        </NavigationGroup>
                    </div>
                </div>
            </SidebarShell>
            <div className={`hidden shrink-0 transition-all duration-300 lg:block ${navCollapsed ? 'w-20' : 'w-72'}`} />
        </>
    );
};
