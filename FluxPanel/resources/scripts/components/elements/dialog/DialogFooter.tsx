import React, { useContext } from 'react';
import { DialogContext } from './';
import { useDeepCompareEffect } from '@/plugins/useDeepCompareEffect';

export default ({ children }: { children: React.ReactNode }) => {
    const { setFooter } = useContext(DialogContext);

    useDeepCompareEffect(() => {
        setFooter(
            <div className={'px-6 py-4 flex items-center justify-end space-x-3 rounded-b'} style={{ background: '#080b11', borderTop: '1px solid #17202e' }}>{children}</div>
        );
    }, [children]);

    return null;
};
