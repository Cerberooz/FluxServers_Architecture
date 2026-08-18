import React, { useEffect, useState } from 'react';
import tw from 'twin.macro';
import http from '@/api/http';
import Button from '@/components/elements/Button';
import Modal from '@/components/elements/Modal';
import Spinner from '@/components/elements/Spinner';
import ServerContentBlock from '@/components/elements/ServerContentBlock';
import { ServerContext } from '@/state/server';
import { useFlashKey } from '@/plugins/useFlash';

type Candidate = {
    egg_id: number;
    egg_name: string;
    platform: string;
    versions: string[];
    default_version?: string | null;
    version_variable?: string | null;
    builds: string[];
    default_build?: string | null;
    build_variable?: string | null;
    custom_version_allowed: boolean;
    custom_build_allowed: boolean;
};

type Platform = {
    name: string;
    initial: string;
    kind: 'server' | 'modded' | 'proxy';
    description: string;
    versions_count: number;
    candidates: Candidate[];
};

type Response = {
    attributes: {
        current: { platform: string; egg_name: string; version?: string | null; build?: string | null };
        platforms: Platform[];
    };
};

type Selection = { candidate: Candidate; version?: string };

export default () => {
    const uuid = ServerContext.useStoreState((state) => state.server.data!.uuid);
    const { clearAndAddHttpError } = useFlashKey('server:version-changer');
    const [data, setData] = useState<Response['attributes']>();
    const [platform, setPlatform] = useState<Platform>();
    const [selection, setSelection] = useState<Selection>();
    const [notice, setNotice] = useState<string>();

    const load = () => http.get<Response>(`/api/client/servers/${uuid}/version-changer`)
        .then(({ data: response }) => setData(response.attributes));

    useEffect(() => { load().catch(clearAndAddHttpError); }, [uuid]);

    return <ServerContentBlock title={'Version Changer'} showFlashKey={'server:version-changer'}>
        {!data ? <Spinner size={'large'} centered /> : <>
            <div css={tw`mb-6 border-b border-neutral-700 pb-5`}>
                <h2 css={tw`text-lg font-semibold text-neutral-100`}>Version Changer</h2>
                <p css={tw`mt-1 text-sm text-neutral-400`}>Choose server software, then select the Minecraft version and build you want to install.</p>
            </div>

            {notice && <div css={tw`mb-5 flex items-start justify-between gap-4 rounded border border-blue-700 bg-blue-900 bg-opacity-20 p-4 text-sm text-blue-100`}>
                <span>{notice}</span>
                <button type={'button'} css={tw`text-blue-200 hover:text-white`} onClick={() => setNotice(undefined)} aria-label={'Dismiss notification'}>×</button>
            </div>}

            <section css={tw`mb-8 rounded border border-neutral-700 bg-neutral-900 p-4`}>
                <p css={tw`text-xs font-medium uppercase tracking-wide text-neutral-500`}>Current installation</p>
                <div css={tw`mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1`}>
                    <p css={tw`text-base font-semibold text-neutral-100`}>{data.current.platform}{data.current.version ? ` ${data.current.version}` : ''}</p>
                    {data.current.build && <p css={tw`text-sm text-neutral-400`}>Build {data.current.build}</p>}
                    <p css={tw`ml-auto text-xs text-neutral-400`}>Changing software can require compatible plugins or mods.</p>
                </div>
            </section>

            {!platform ? <SoftwareList platforms={data.platforms} onSelect={setPlatform} /> : <VersionList platform={platform} onBack={() => setPlatform(undefined)} onSelect={(candidate, version) => setSelection({ candidate, version })} />}
            {selection && <InstallModal
                selection={selection}
                onDismiss={() => setSelection(undefined)}
                onInstall={(payload) => http.post(`/api/client/servers/${uuid}/version-changer/install`, payload)
                    .then(() => {
                        setSelection(undefined);
                        setPlatform(undefined);
                        setNotice(`Installation has started. ${payload.wipe ? 'Existing server files were removed before the new installation.' : 'Existing files were kept.'}`);
                        return load();
                    })
                    .catch(clearAndAddHttpError)}
            />}
        </>}
    </ServerContentBlock>;
};

const SoftwareList = ({ platforms, onSelect }: { platforms: Platform[]; onSelect: (platform: Platform) => void }) => <section>
    <h3 css={tw`text-base font-semibold text-neutral-100`}>Available software</h3>
    <p css={tw`mt-1 text-sm text-neutral-400`}>Only eggs configured in this Panel are shown, so every option has an approved install script.</p>
    {!platforms.length ? <div css={tw`mt-5 rounded border border-yellow-700 bg-neutral-900 p-4 text-sm text-yellow-200`}>No supported Minecraft or proxy eggs are installed yet. Import a Paper, Folia, Velocity, or other supported egg in the admin panel first.</div> : <div css={tw`mt-5 grid gap-4 lg:grid-cols-2`}>
        {platforms.map((platform) => <button key={platform.name} type={'button'} onClick={() => onSelect(platform)} className={'group'} css={tw`rounded border border-neutral-700 bg-neutral-900 p-4 text-left transition-colors hover:border-blue-600 hover:bg-neutral-800`}>
            <div css={tw`flex items-start gap-3`}>
                <span css={tw`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded border border-neutral-600 bg-neutral-800 text-base font-semibold text-neutral-100`}>{platform.initial}</span>
                <span css={tw`min-w-0 flex-1`}>
                    <span css={tw`block text-sm font-semibold text-neutral-100`}>{platform.name}</span>
                    <span css={tw`mt-1 block text-xs text-neutral-400`}>{platform.description}</span>
                </span>
                <span css={tw`text-right`}><span css={tw`block text-xs text-neutral-400`}>{platform.versions_count} {platform.versions_count === 1 ? 'version' : 'versions'}</span><span css={tw`mt-2 inline-block rounded border border-neutral-600 px-2 py-1 text-[10px] font-semibold uppercase text-neutral-400`}>{platform.kind}</span></span>
            </div>
            <span css={tw`mt-3 block text-right text-xs font-semibold text-blue-400 group-hover:text-blue-300`}>Browse →</span>
        </button>)}
    </div>}
</section>;

const VersionList = ({ platform, onBack, onSelect }: { platform: Platform; onBack: () => void; onSelect: (candidate: Candidate, version?: string) => void }) => <section>
    <button type={'button'} onClick={onBack} css={tw`mb-5 text-sm font-semibold text-blue-400 hover:text-blue-300`}>← Version Changer</button>
    <h3 css={tw`text-xl font-semibold text-neutral-100`}>{platform.name}</h3>
    <p css={tw`mt-1 text-sm text-neutral-400`}>Select a version supported by this launcher. You can choose a specific build before installing.</p>
    <div css={tw`mt-6 grid gap-4 lg:grid-cols-2`}>
        {platform.candidates.flatMap((candidate) => {
            const versions = candidate.versions.length ? candidate.versions : [candidate.default_version || 'Version set by egg'];
            return versions.map((version) => <div key={`${candidate.egg_id}-${version}`} css={tw`flex items-center gap-3 rounded border border-neutral-700 bg-neutral-900 p-4`}>
                <span css={tw`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded border border-neutral-600 bg-neutral-800 text-xs font-semibold text-neutral-100`}>{platform.initial}</span>
                <div css={tw`min-w-0 flex-1`}><p css={tw`text-sm font-semibold text-neutral-100`}>{version}</p><p css={tw`mt-1 truncate text-xs text-neutral-400`}>{candidate.egg_name}</p></div>
                <Button size={'xsmall'} color={'primary'} onClick={() => onSelect(candidate, candidate.version_variable ? version : undefined)}>Install</Button>
            </div>);
        })}
    </div>
    <p css={tw`mt-5 text-xs text-neutral-500`}>A backup is recommended before switching implementations. Installing a different platform can affect plugin and mod compatibility.</p>
</section>;

const InstallModal = ({ selection, onDismiss, onInstall }: { selection: Selection; onDismiss: () => void; onInstall: (payload: { egg_id: number; version?: string; build?: string; wipe: boolean; confirm: boolean }) => Promise<unknown> }) => {
    const { candidate } = selection;
    const [version, setVersion] = useState(selection.version || candidate.default_version || '');
    const [build, setBuild] = useState(candidate.default_build || candidate.builds[0] || '');
    const [wipe, setWipe] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    const install = () => {
        setSubmitting(true);
        onInstall({ egg_id: candidate.egg_id, version: candidate.version_variable ? version : undefined, build: candidate.build_variable ? build : undefined, wipe, confirm: true })
            .finally(() => setSubmitting(false));
    };

    return <Modal visible onDismissed={onDismiss}>
        <h2 css={tw`text-lg font-semibold text-neutral-100`}>Install {candidate.platform}{version ? ` ${version}` : ''}</h2>
        <p css={tw`mt-2 text-sm text-neutral-400`}>Choose a build and confirm how the server files should be handled.</p>
        {candidate.version_variable && <label css={tw`mt-5 block text-xs font-medium uppercase tracking-wide text-neutral-500`}>Minecraft version
            {candidate.custom_version_allowed ? <input css={tw`mt-2 w-full rounded border border-neutral-600 bg-neutral-900 px-3 py-2 text-sm text-neutral-100`} value={version} onChange={(event) => setVersion(event.target.value)} /> : <p css={tw`mt-2 rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100`}>{version}</p>}
        </label>}
        {candidate.build_variable && <label css={tw`mt-5 block text-xs font-medium uppercase tracking-wide text-neutral-500`}>Build
            {candidate.custom_build_allowed ? <input css={tw`mt-2 w-full rounded border border-neutral-600 bg-neutral-900 px-3 py-2 text-sm text-neutral-100`} value={build} onChange={(event) => setBuild(event.target.value)} /> : <select css={tw`mt-2 w-full rounded border border-neutral-600 bg-neutral-900 px-3 py-2 text-sm text-neutral-100`} value={build} onChange={(event) => setBuild(event.target.value)}>{candidate.builds.map((value) => <option key={value} value={value}>Build {value}</option>)}</select>}
        </label>}
        <label css={tw`mt-5 flex cursor-pointer items-start gap-3 rounded border border-neutral-700 bg-neutral-900 p-3`}>
            <input type={'checkbox'} checked={wipe} onChange={(event) => setWipe(event.target.checked)} css={tw`mt-1`} />
            <span><span css={tw`block text-sm font-medium text-neutral-100`}>Wipe server files before installing</span><span css={tw`mt-1 block text-xs text-neutral-400`}>Deletes existing server files before installation. This cannot be undone.</span></span>
        </label>
        <div css={tw`mt-6 flex justify-end gap-3`}><Button color={'grey'} onClick={onDismiss}>Cancel</Button><Button color={'primary'} isLoading={submitting} disabled={submitting || Boolean(candidate.version_variable && !version.trim())} onClick={install}>Install</Button></div>
    </Modal>;
};
