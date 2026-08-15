import React from 'react';
import { Route } from 'react-router';
import { SwitchTransition } from 'react-transition-group';
import CSSTransition from 'react-transition-group/CSSTransition';
import styled from 'styled-components/macro';
import tw from 'twin.macro';

const StyledSwitchTransition = styled(SwitchTransition)`
    ${tw`relative`};

    & section {
        ${tw`absolute w-full top-0 left-0`};
    }

    .tab-slide-enter,
    .tab-slide-exit {
        will-change: transform, opacity;
    }

    .tab-slide-enter {
        opacity: 0;
        transform: translate3d(24px, 0, 0);
    }

    .tab-slide-enter-active {
        opacity: 1;
        transform: translate3d(0, 0, 0);
        transition: transform 180ms ease-out, opacity 180ms ease-out;
    }

    .tab-slide-exit {
        opacity: 1;
        transform: translate3d(0, 0, 0);
    }

    .tab-slide-exit-active {
        opacity: 0;
        transform: translate3d(-24px, 0, 0);
        transition: transform 180ms ease-in, opacity 180ms ease-in;
    }
`;

const TransitionRouter: React.FC = ({ children }) => {
    return (
        <Route
            render={({ location }) => (
                <StyledSwitchTransition>
                    <CSSTransition timeout={180} classNames={'tab-slide'} key={location.pathname + location.search} in appear unmountOnExit>
                        <section>{children}</section>
                    </CSSTransition>
                </StyledSwitchTransition>
            )}
        />
    );
};

export default TransitionRouter;
