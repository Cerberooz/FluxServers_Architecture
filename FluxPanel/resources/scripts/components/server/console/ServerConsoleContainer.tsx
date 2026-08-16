import React, { memo, useEffect, useMemo, useState } from 'react';
import { ServerContext } from '@/state/server';
import Can from '@/components/elements/Can';
import ServerContentBlock from '@/components/elements/ServerContentBlock';
import isEqual from 'react-fast-compare';
import Spinner from '@/components/elements/Spinner';
import Features from '@feature/Features';
import Console from '@/components/server/console/Console';
import StatGraphs from '@/components/server/console/StatGraphs';
import PowerButtons from '@/components/server/console/PowerButtons';
import ServerDetailsBlock from '@/components/server/console/ServerDetailsBlock';
import { Alert } from '@/components/elements/alert';
import { ip } from '@/lib/formatters';
import { SocketEvent, SocketRequest } from '@/components/server/events';
import useWebsocketEvent from '@/plugins/useWebsocketEvent';
import UptimeDuration from '@/components/server/UptimeDuration';
import CopyOnClick from '@/components/elements/CopyOnClick';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCopy } from '@fortawesome/free-solid-svg-icons';

export type PowerAction = 'start' | 'stop' | 'restart' | 'kill';

const ServerConsoleContainer = () => {
    const server = ServerContext.useStoreState((state) => state.server.data!);
    const status = ServerContext.useStoreState((state) => state.status.value);
    const connected = ServerContext.useStoreState((state) => state.socket.connected);
    const instance = ServerContext.useStoreState((state) => state.socket.instance);
    const isInstalling = ServerContext.useStoreState((state) => state.server.isInstalling);
    const isTransferring = ServerContext.useStoreState((state) => state.server.data!.isTransferring);
    const eggFeatures = ServerContext.useStoreState((state) => state.server.data!.eggFeatures, isEqual);
    const isNodeUnderMaintenance = ServerContext.useStoreState((state) => state.server.data!.isNodeUnderMaintenance);
    const allocation = useMemo(() => {
        const primary = server.allocations.find((item) => item.isDefault);
        return primary ? `${primary.alias || ip(primary.ip)}:${primary.port}` : 'Not assigned';
    }, [server.allocations]);
    const [uptime, setUptime] = useState(0);

    useEffect(() => {
        if (connected && instance) {
            instance.send(SocketRequest.SEND_STATS);
        }
    }, [connected, instance]);

    useWebsocketEvent(SocketEvent.STATS, (data) => {
        try {
            setUptime(JSON.parse(data).uptime || 0);
        } catch (e) {
            // Keep the last known uptime when Wings sends malformed data.
        }
    });

    return (
        <ServerContentBlock title={'Console'}>
            {(isNodeUnderMaintenance || isInstalling || isTransferring) && (
                <Alert type={'warning'} className={'mb-4'}>
                    {isNodeUnderMaintenance
                        ? 'The node of this server is currently under maintenance and all actions are unavailable.'
                        : isInstalling
                        ? 'This server is currently running its installation process and most actions are unavailable.'
                        : 'This server is currently being transferred to another node and all actions are unavailable.'}
                </Alert>
            )}
            <div className={'fluid-console-identity'}>
                <div>
                    <span>Address</span>
                    <CopyOnClick text={allocation} showInNotification={false}>
                        <button type={'button'} className={'fluid-console-copy-address'} title={'Copy server address'}>
                            <strong>{allocation}</strong><FontAwesomeIcon icon={faCopy} />
                        </button>
                    </CopyOnClick>
                </div>
                <div><span>Uptime</span><strong>{uptime > 0 ? <UptimeDuration uptime={uptime / 1000} /> : status === 'running' ? 'Starting' : 'Offline'}</strong></div>
                <div><span>Node</span><strong>{server.node}</strong></div>
                <div><span>Region</span><strong>{server.nodeLocation || 'Not set'}</strong></div>
            </div>
            <div className={'fluid-console-layout'}>
                <section className={'fluid-console-surface'}>
                    <header>
                        <div><h2>Live console</h2><p>Realtime server output</p></div>
                        <Can action={['control.start', 'control.stop', 'control.restart']} matchAny>
                            <PowerButtons className={'fluid-console-controls'} />
                        </Can>
                    </header>
                    <div className={'fluid-console-terminal'}><Spinner.Suspense><Console /></Spinner.Suspense></div>
                </section>
                <section className={'fluid-console-surface fluid-console-resources'}>
                    <header><div><h2>Live resources</h2><p>Current server usage</p></div></header>
                    <ServerDetailsBlock />
                </section>
            </div>
            <div className={'fluid-console-graphs'}>
                <Spinner.Suspense>
                    <StatGraphs />
                </Spinner.Suspense>
            </div>
            <Features enabled={eggFeatures} />
        </ServerContentBlock>
    );
};

export default memo(ServerConsoleContainer, isEqual);
