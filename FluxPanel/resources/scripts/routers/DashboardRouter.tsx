import React from 'react';
import { NavLink, Redirect, Route, Switch } from 'react-router-dom';
import NavigationBar from '@/components/NavigationBar';
import DashboardContainer from '@/components/dashboard/DashboardContainer';
import { NotFound } from '@/components/elements/ScreenBlock';
import TransitionRouter from '@/TransitionRouter';
import SubNavigation from '@/components/elements/SubNavigation';
import { useLocation } from 'react-router';
import Spinner from '@/components/elements/Spinner';
import routes from '@/routers/routes';
import BillingContainer from '@/components/dashboard/BillingContainer';
import SupportContainer from '@/components/dashboard/SupportContainer';

export default () => {
    const location = useLocation();

    return (
        <>
            <NavigationBar />
            <div>
                {location.pathname.startsWith('/account') && !['/account/billing', '/account/support'].includes(location.pathname) && (
                    <SubNavigation>
                        <div>
                            {routes.account
                                .filter((route) => !!route.name && !['Billing', 'Support'].includes(route.name))
                                .map(({ path, name, exact = false }) => (
                                    <NavLink key={path} to={`/account/${path}`.replace('//', '/')} exact={exact}>
                                        {name}
                                    </NavLink>
                                ))}
                        </div>
                    </SubNavigation>
                )}
                <TransitionRouter>
                    <React.Suspense fallback={<Spinner centered />}>
                        <Switch location={location}>
                            <Route path={'/'} exact>
                                <DashboardContainer />
                            </Route>
                            {routes.account.filter(({ name }) => !['Billing', 'Support'].includes(name || '')).map(({ path, component: Component }) => (
                                <Route key={path} path={`/account/${path}`.replace('//', '/')} exact>
                                    <Component />
                                </Route>
                            ))}
                            {/* Billing and Support are dashboard sections, not account settings. */}
                            <Route path={'/billing'} exact>
                                <BillingContainer />
                            </Route>
                            <Route path={'/support'} exact>
                                <SupportContainer />
                            </Route>
                            {/* Preserve bookmarks from the previous URL structure. */}
                            <Route path={'/account/billing'} exact>
                                <Redirect to={'/billing'} />
                            </Route>
                            <Route path={'/account/support'} exact>
                                <Redirect to={'/support'} />
                            </Route>
                            <Route path={'*'}>
                                <NotFound />
                            </Route>
                        </Switch>
                    </React.Suspense>
                </TransitionRouter>
            </div>
        </>
    );
};
