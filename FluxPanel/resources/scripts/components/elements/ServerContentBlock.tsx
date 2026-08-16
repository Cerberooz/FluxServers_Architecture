import PageContentBlock, { PageContentBlockProps } from '@/components/elements/PageContentBlock';
import React from 'react';
import { ServerContext } from '@/state/server';

interface Props extends PageContentBlockProps {
    title: string;
    showServerHeader?: boolean;
}

const ServerContentBlock: React.FC<Props> = ({ title, children, showServerHeader = true, ...props }) => {
    const server = ServerContext.useStoreState((state) => state.server.data!);
    const status = ServerContext.useStoreState((state) => state.status.value);
    const state = status || server.status || 'offline';

    return (
        <PageContentBlock title={`${server.name} | ${title}`} {...props}>
            <div className={'fluid-server-page'}>
                {showServerHeader && (
                    <header className={'fluid-server-page__header'}>
                        <div>
                            <h1>{server.name}</h1>
                            <p>{title} <span>&middot;</span> {server.eggName}</p>
                        </div>
                        <div className={`fluid-server-page__status fluid-server-page__status--${state}`}>
                            <i /> {state}
                        </div>
                    </header>
                )}
                <div className={'fluid-server-page__content'}>{children}</div>
            </div>
        </PageContentBlock>
    );
};

export default ServerContentBlock;
