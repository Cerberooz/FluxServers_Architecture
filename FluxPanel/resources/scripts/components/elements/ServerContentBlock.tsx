import PageContentBlock, { PageContentBlockProps } from '@/components/elements/PageContentBlock';
import React from 'react';
import { ServerContext } from '@/state/server';
import useSWR from 'swr';
import getRuntimeMetadata from '@/api/server/getRuntimeMetadata';

interface Props extends PageContentBlockProps {
    title: string;
    showServerHeader?: boolean;
}

const ServerContentBlock: React.FC<Props> = ({ title, children, showServerHeader = true, ...props }) => {
    const server = ServerContext.useStoreState((state) => state.server.data!);
    const status = ServerContext.useStoreState((state) => state.status.value);
    const state = status || server.status || 'offline';
    const { data: runtime } = useSWR(['server-runtime-metadata', server.uuid], () => getRuntimeMetadata(server.uuid));
    const software = runtime?.minecraftVersion && runtime.software ? `Minecraft ${runtime.minecraftVersion} · ${runtime.software}` : 'Unknown';
    // Velocity stays in Wings' "starting" state for its whole process lifetime.
    // It is nevertheless online once the verified Velocity process is present.
    const displayedState = runtime?.software === 'Velocity' && state === 'starting' ? 'running' : state;

    return (
        <PageContentBlock title={`${server.name} | ${title}`} {...props}>
            <div className={'fluid-server-page'}>
                {showServerHeader && (
                    <header className={'fluid-server-page__header'}>
                        <div>
                            <h1>{server.name}</h1>
                            <p>{title} <span>&middot;</span> {software}</p>
                        </div>
                        <div className={`fluid-server-page__status fluid-server-page__status--${displayedState}`}>
                            <i /> {displayedState}
                        </div>
                    </header>
                )}
                <div className={'fluid-server-page__content'}>{children}</div>
            </div>
        </PageContentBlock>
    );
};

export default ServerContentBlock;
