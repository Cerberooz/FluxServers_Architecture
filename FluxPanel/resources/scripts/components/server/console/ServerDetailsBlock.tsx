import React, { useEffect, useMemo, useState } from 'react';
import { bytesToString, mbToBytes } from '@/lib/formatters';
import { ServerContext } from '@/state/server';
import { SocketEvent, SocketRequest } from '@/components/server/events';
import useWebsocketEvent from '@/plugins/useWebsocketEvent';
import classNames from 'classnames';

type Stats = Record<'memory' | 'cpu' | 'disk' | 'uptime' | 'rx' | 'tx', number>;

const ServerDetailsBlock = ({ className }: { className?: string }) => {
    const [stats, setStats] = useState<Stats>({ memory: 0, cpu: 0, disk: 0, uptime: 0, tx: 0, rx: 0 });

    const status = ServerContext.useStoreState((state) => state.status.value);
    const connected = ServerContext.useStoreState((state) => state.socket.connected);
    const instance = ServerContext.useStoreState((state) => state.socket.instance);
    const limits = ServerContext.useStoreState((state) => state.server.data!.limits);

    const textLimits = useMemo(
        () => ({
            cpu: limits?.cpu ? `${limits.cpu}%` : null,
            memory: limits?.memory ? bytesToString(mbToBytes(limits.memory)) : null,
            disk: limits?.disk ? bytesToString(mbToBytes(limits.disk)) : null,
        }),
        [limits]
    );

    const percentage = (value: number, limit: number) => limit > 0 ? Math.min(100, Math.round((value / limit) * 100)) : 0;
    const memoryLimit = mbToBytes(limits.memory);
    const diskLimit = mbToBytes(limits.disk);
    const resources = [
        { label: 'CPU load', value: status === 'offline' ? 'Offline' : `${stats.cpu.toFixed(2)}%`, detail: `of ${textLimits.cpu || 'unlimited'} allocation` },
        { label: 'Memory', value: status === 'offline' ? 'Offline' : `${bytesToString(stats.memory)} / ${textLimits.memory || 'unlimited'}`, detail: status === 'offline' ? '' : `${percentage(stats.memory, memoryLimit)}% allocated` },
        { label: 'Disk', value: `${bytesToString(stats.disk)} / ${textLimits.disk || 'unlimited'}`, detail: diskLimit > 0 ? `${bytesToString(Math.max(diskLimit - stats.disk, 0))} available` : '' },
        { label: 'Network in', value: status === 'offline' ? 'Offline' : bytesToString(stats.rx), detail: status === 'offline' ? '' : 'current session' },
        { label: 'Network out', value: status === 'offline' ? 'Offline' : bytesToString(stats.tx), detail: status === 'offline' ? '' : 'current session' },
    ];

    useEffect(() => {
        if (!connected || !instance) {
            return;
        }

        instance.send(SocketRequest.SEND_STATS);
    }, [instance, connected]);

    useWebsocketEvent(SocketEvent.STATS, (data) => {
        let stats: any = {};
        try {
            stats = JSON.parse(data);
        } catch (e) {
            return;
        }

        setStats({
            memory: stats.memory_bytes,
            cpu: stats.cpu_absolute,
            disk: stats.disk_bytes,
            tx: stats.network.tx_bytes,
            rx: stats.network.rx_bytes,
            uptime: stats.uptime || 0,
        });
    });

    return (
        <div className={classNames('fluid-console-resource-list', className)}>
            {resources.map((resource) => (
                <div className={'fluid-console-resource-row'} key={resource.label}>
                    <span>{resource.label}</span>
                    <div><strong>{resource.value}</strong>{resource.detail && <small>{resource.detail}</small>}</div>
                </div>
            ))}
        </div>
    );
};

export default ServerDetailsBlock;
