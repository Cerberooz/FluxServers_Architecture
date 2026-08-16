import React from 'react';

export default ({ uptime }: { uptime: number }) => {
    const totalSeconds = Number.isFinite(uptime) && uptime >= 0 ? Math.floor(uptime) : 0;
    const days = Math.floor(totalSeconds / (24 * 60 * 60));
    const hours = Math.floor((totalSeconds / 60 / 60) % 24);
    const remainder = totalSeconds - days * 24 * 60 * 60 - hours * 60 * 60;
    const minutes = Math.floor((remainder / 60) % 60);
    const seconds = remainder % 60;

    if (days > 0) {
        return (
            <>
                {days}d {hours}h {minutes}m
            </>
        );
    }

    return (
        <>
            {hours}h {minutes}m {seconds}s
        </>
    );
};
