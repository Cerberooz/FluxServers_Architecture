import React, { useEffect, useState } from 'react';
import tw from 'twin.macro';
import http from '@/api/http';
import Button from '@/components/elements/Button';
import Spinner from '@/components/elements/Spinner';
import ServerContentBlock from '@/components/elements/ServerContentBlock';
import { ServerContext } from '@/state/server';
import { useFlashKey } from '@/plugins/useFlash';

type Domain = { id: number; domain: string };
type Subdomain = { id: number; hostname: string; status: string; last_error?: string; connection_address: string };

export default () => {
    const uuid = ServerContext.useStoreState((state) => state.server.data!.uuid);
    const { clearAndAddHttpError } = useFlashKey('server:subdomains');
    const [domains, setDomains] = useState<Domain[]>();
    const [subdomains, setSubdomains] = useState<Subdomain[]>();
    const [domainId, setDomainId] = useState('');
    const [label, setLabel] = useState('');
    const [editing, setEditing] = useState<Subdomain | null>(null);
    const [editLabel, setEditLabel] = useState('');

    const load = () => Promise.all([
        http.get(`/api/client/servers/${uuid}/subdomains`),
        http.get(`/api/client/servers/${uuid}/subdomains/domains`),
    ]).then(([subdomainResponse, domainResponse]) => {
        setSubdomains(subdomainResponse.data.data);
        setDomains(domainResponse.data.data);
    });

    useEffect(() => {
        load().catch(clearAndAddHttpError);
    }, []);

    const create = () => http.post(`/api/client/servers/${uuid}/subdomains`, { domain_id: Number(domainId), label })
        .then(() => {
            setLabel('');
            return load();
        })
        .catch(clearAndAddHttpError);

    const remove = (id: number) => http.delete(`/api/client/servers/${uuid}/subdomains/${id}`).then(load).catch(clearAndAddHttpError);

    const saveRename = () => {
        if (!editing || !editLabel) return;
        http.patch(`/api/client/servers/${uuid}/subdomains/${editing.id}`, { label: editLabel })
            .then(() => {
                setEditing(null);
                setEditLabel('');
                return load();
            })
            .catch(clearAndAddHttpError);
    };

    return <ServerContentBlock title={'Subdomains'} showFlashKey={'server:subdomains'}>
        {!domains || !subdomains ? <Spinner size={'large'} centered /> : <>
            <p css={tw`mb-6 text-sm text-neutral-300`}>Create a friendly address for this server. DNS always follows this server&apos;s primary allocation.</p>
            <div css={tw`mb-8 grid gap-3 rounded bg-neutral-800 p-4 sm:grid-cols-3`}>
                <input css={tw`rounded border border-neutral-600 bg-neutral-900 px-3 py-2 text-neutral-100`} value={label} onChange={(event) => setLabel(event.target.value.toLowerCase())} placeholder={'myserver'} maxLength={63} />
                <select css={tw`rounded border border-neutral-600 bg-neutral-900 px-3 py-2 text-neutral-100`} value={domainId} onChange={(event) => setDomainId(event.target.value)}>
                    <option value={''}>Select domain</option>
                    {domains.map((domain) => <option key={domain.id} value={domain.id}>{domain.domain}</option>)}
                </select>
                <Button color={'primary'} disabled={!label || !domainId} onClick={create}>Create Subdomain</Button>
            </div>
            <div css={tw`space-y-3`}>
                {subdomains.map((subdomain) => <div key={subdomain.id} css={tw`rounded bg-neutral-800 p-4`}>
                    {editing?.id === subdomain.id ? <div css={tw`flex flex-col gap-3 sm:flex-row sm:items-center`}>
                        <input css={tw`flex-1 rounded border border-neutral-600 bg-neutral-900 px-3 py-2 text-neutral-100`} value={editLabel} onChange={(event) => setEditLabel(event.target.value.toLowerCase())} maxLength={63} autoFocus />
                        <Button color={'primary'} disabled={!editLabel} onClick={saveRename}>Save</Button>
                        <Button color={'grey'} onClick={() => setEditing(null)}>Cancel</Button>
                    </div> : <div css={tw`flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between`}>
                        <div>
                            <p css={tw`font-medium text-neutral-100`}>{subdomain.hostname}</p>
                            <p css={tw`mt-1 text-sm text-neutral-400`}>{subdomain.status}{subdomain.last_error ? ` - ${subdomain.last_error}` : ''}</p>
                        </div>
                        <div css={tw`flex flex-wrap gap-3`}>
                            <Button color={'grey'} onClick={() => navigator.clipboard.writeText(subdomain.connection_address)}>Copy address</Button>
                            <Button color={'grey'} onClick={() => { setEditing(subdomain); setEditLabel(subdomain.hostname.split('.')[0]); }}>Rename</Button>
                            <Button color={'red'} onClick={() => remove(subdomain.id)}>Delete</Button>
                        </div>
                    </div>}
                </div>)}
                {!subdomains.length && <p css={tw`text-sm text-neutral-400`}>No subdomains are assigned to this server.</p>}
            </div>
        </>}
    </ServerContentBlock>;
};
