import React, { useEffect, useRef, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faHdd, faMemory, faMicrochip, faServer } from '@fortawesome/free-solid-svg-icons';
import { Link } from 'react-router-dom';
import { Server } from '@/api/server/getServer';
import getServerResourceUsage, { ServerStats } from '@/api/server/getServerResourceUsage';
import { bytesToString } from '@/lib/formatters';
import tw from 'twin.macro';
import styled from 'styled-components/macro';

const Row = styled(Link)`
    ${tw`grid items-center border-b border-neutral-700 py-4 text-xs no-underline transition-colors hover:bg-neutral-900`};
    grid-template-columns: 340px 150px 140px 100px 160px 160px 130px;
    min-height: 72px;
`;

const Dot = styled.span<{ $online: boolean }>`
    ${tw`mr-2 inline-block h-2 w-2 rounded-full`};
    background: ${({ $online }) => ($online ? '#25d281' : '#687994')};
`;

type Timer = ReturnType<typeof setInterval>;

export default ({ server, className }: { server: Server; className?: string }) => {
    const interval = useRef<Timer>(null) as React.MutableRefObject<Timer>;
    const [stats, setStats] = useState<ServerStats | null>(null);
    const [failed, setFailed] = useState(false);

    const refresh = () => getServerResourceUsage(server.uuid).then((data) => { setStats(data); setFailed(false); }).catch(() => setFailed(true));

    useEffect(() => {
        if (server.status === 'suspended' || server.isNodeUnderMaintenance) return;
        refresh().then(() => { interval.current = setInterval(refresh, 30000); });
        return () => { if (interval.current) clearInterval(interval.current); };
    }, [server.uuid, server.status, server.isNodeUnderMaintenance]);

    const online = stats?.status === 'running';
    const status = server.status === 'suspended' ? 'Suspended' : server.isNodeUnderMaintenance ? 'Maintenance' : failed ? 'Unavailable' : stats ? (online ? 'Online' : 'Offline') : 'Loading';
    const cpu = stats ? `${stats.cpuUsagePercent.toFixed(2)}%` : '—';
    const memory = stats ? bytesToString(stats.memoryUsageInBytes) : '—';
    const disk = stats ? bytesToString(stats.diskUsageInBytes) : '—';

    return (
        <Row to={`/server/${server.id}`} className={className}>
            <div css={tw`flex items-center pl-4 pr-4`}><FontAwesomeIcon icon={faServer} css={tw`mr-3 text-neutral-500`} /><div><p css={tw`font-semibold text-neutral-100`}>{server.name}</p>{server.description && <p css={tw`mt-1 truncate text-[10px] text-neutral-500`}>{server.description}</p>}</div></div>
            <div css={tw`truncate text-neutral-400`} title={server.nodeLocation || undefined}>{server.nodeLocation || 'Not set'}</div>
            <div css={tw`text-neutral-300`}><Dot $online={online} />{status}</div>
            <div css={tw`text-neutral-300`}><FontAwesomeIcon icon={faMicrochip} css={tw`mr-2 text-neutral-500`} />{cpu}</div>
            <div css={tw`text-neutral-300`}><FontAwesomeIcon icon={faMemory} css={tw`mr-2 text-neutral-500`} />{memory}</div>
            <div css={tw`text-neutral-300`}><FontAwesomeIcon icon={faHdd} css={tw`mr-2 text-neutral-500`} />{disk}</div>
            <div css={tw`pr-4 text-right font-semibold text-blue-400`}>View →</div>
        </Row>
    );
};
