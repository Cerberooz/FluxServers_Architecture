import React, { useEffect, useState } from 'react';
import { ServerContext } from '@/state/server';
import Modal from '@/components/elements/Modal';
import tw from 'twin.macro';
import Button from '@/components/elements/Button';
import saveFileContents from '@/api/server/files/saveFileContents';
import getFileContents from '@/api/server/files/getFileContents';
import FlashMessageRender from '@/components/FlashMessageRender';
import useFlash from '@/plugins/useFlash';
import { SocketEvent, SocketRequest } from '@/components/server/events';

const EulaModalFeature = () => {
    const [visible, setVisible] = useState(false);
    const [loading, setLoading] = useState(false);

    const uuid = ServerContext.useStoreState((state) => state.server.data!.uuid);
    const status = ServerContext.useStoreState((state) => state.status.value);
    const { clearFlashes, clearAndAddHttpError } = useFlash();
    const { connected, instance } = ServerContext.useStoreState((state) => state.socket);

    useEffect(() => {
        if (!connected || !instance || status === 'running') return;

        const listener = (line: string) => {
            if (line.toLowerCase().indexOf('you need to agree to the eula in order to run the server') >= 0) {
                setVisible(true);
            }
        };

        instance.addListener(SocketEvent.CONSOLE_OUTPUT, listener);

        return () => {
            instance.removeListener(SocketEvent.CONSOLE_OUTPUT, listener);
        };
    }, [connected, instance, status]);

    // The server can be started automatically during provisioning, before the
    // console listener is attached. Check the file as well so the EULA prompt
    // is still shown when Wings has already stopped the server.
    useEffect(() => {
        if (status === 'running') return;

        let cancelled = false;
        getFileContents(uuid, 'eula.txt')
            .then((contents) => {
                if (!cancelled && /^\s*eula\s*=\s*false\s*$/im.test(contents)) setVisible(true);
            })
            .catch(() => {
                // The file may not exist until the first installation has run.
            });

        return () => {
            cancelled = true;
        };
    }, [uuid, status]);

    const onAcceptEULA = () => {
        setLoading(true);
        clearFlashes('feature:eula');

        saveFileContents(uuid, 'eula.txt', 'eula=true')
            .then(() => {
                if (status === 'offline' && instance) {
                    instance.send(SocketRequest.SET_STATE, 'restart');
                }

                setLoading(false);
                setVisible(false);
            })
            .catch((error) => {
                console.error(error);
                clearAndAddHttpError({ key: 'feature:eula', error });
            })
            .then(() => setLoading(false));
    };

    useEffect(() => {
        clearFlashes('feature:eula');
    }, []);

    return (
        <Modal
            visible={visible}
            onDismissed={() => setVisible(false)}
            closeOnBackground={false}
            showSpinnerOverlay={loading}
        >
            <FlashMessageRender key={'feature:eula'} css={tw`mb-4`} />
            <h2 css={tw`text-2xl mb-4 text-neutral-100`}>Accept Minecraft&reg; EULA</h2>
            <p css={tw`text-neutral-200`}>
                By pressing {'"I Accept"'} below you are indicating your agreement to the&nbsp;
                <a
                    target={'_blank'}
                    css={tw`text-primary-300 underline transition-colors duration-150 hover:text-primary-400`}
                    rel={'noreferrer noopener'}
                    href='https://www.minecraft.net/eula'
                >
                    Minecraft&reg; EULA
                </a>
                .
            </p>
            <div css={tw`mt-8 sm:flex items-center justify-end`}>
                <Button isSecondary onClick={() => setVisible(false)} css={tw`w-full sm:w-auto border-transparent`}>
                    Cancel
                </Button>
                <Button onClick={onAcceptEULA} css={tw`mt-4 sm:mt-0 sm:ml-4 w-full sm:w-auto`}>
                    I Accept
                </Button>
            </div>
        </Modal>
    );
};

export default EulaModalFeature;
