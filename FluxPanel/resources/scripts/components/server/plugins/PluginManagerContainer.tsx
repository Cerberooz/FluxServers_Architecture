import React, { useCallback, useEffect, useRef, useState } from 'react';
import tw from 'twin.macro';
import http from '@/api/http';
import Button from '@/components/elements/Button';
import Spinner from '@/components/elements/Spinner';
import ServerContentBlock from '@/components/elements/ServerContentBlock';
import { ServerContext } from '@/state/server';
import { useFlashKey } from '@/plugins/useFlash';

type Version = { id: string; version_number: string };
type Project = { id: string; name: string; author: string; description: string; icon?: string; downloads: number; platforms: string[]; compatible: boolean; reason?: string; version?: Version };
type Installed = { filename: string; name: string; status: string; disabled: boolean; project_id?: string; version_id?: string; latest?: Version; update_available: boolean };
type Dependency = { type: string; project_id?: string; version_id?: string; resolved?: Version };

export default () => {
    const uuid = ServerContext.useStoreState((state) => state.server.data!.uuid);
    const { clearAndAddHttpError } = useFlashKey('server:plugins');
    // Show the server's real plugin directory first. It makes the page useful
    // immediately and avoids implying that an empty Discover search means no
    // plugins are installed.
    const [tab, setTab] = useState<'discover' | 'installed'>('installed');
    const [query, setQuery] = useState('');
    const [projects, setProjects] = useState<Project[]>([]);
    const [searching, setSearching] = useState(false);
    const [installed, setInstalled] = useState<Installed[]>();
    const [context, setContext] = useState<{ supported: boolean; platform?: string; version?: string }>();
    const [confirm, setConfirm] = useState<{ project: Project; dependencies: Dependency[]; updateFilename?: string }>();

    const searchRequest = useRef(0);
    const flashError = useRef(clearAndAddHttpError);
    flashError.current = clearAndAddHttpError;
    const discover = useCallback((term: string) => {
        const request = ++searchRequest.current;
        setSearching(true);

        return http.get(`/api/client/servers/${uuid}/plugins/search`, { params: { query: term } })
            .then(({ data }) => {
                if (request !== searchRequest.current) return;
                setProjects(data.projects);
                setContext(data.context);
            })
            .catch((error) => {
                if (request === searchRequest.current) flashError.current(error);
            })
            .finally(() => {
                if (request === searchRequest.current) setSearching(false);
            });
    }, [uuid]);
    const scanInstalled = () => http.get(`/api/client/servers/${uuid}/plugins/installed`).then(({ data }) => { setInstalled(data.plugins); setContext(data.context); }).catch(clearAndAddHttpError);
    useEffect(() => { scanInstalled(); }, []);
    useEffect(() => {
        const term = query.trim();
        if (!term) {
            searchRequest.current += 1;
            setSearching(false);
            setProjects([]);
            return;
        }

        const timeout = window.setTimeout(() => discover(term), 350);

        return () => window.clearTimeout(timeout);
    }, [query, discover]);
    const installPrompt = (project: Project, updateFilename?: string) => http.get(`/api/client/servers/${uuid}/plugins/projects/${project.id}/dependencies`).then(({ data }) => setConfirm({ project, dependencies: data.data, updateFilename })).catch(clearAndAddHttpError);
    const install = () => { if (!confirm) return; const dependencies = confirm.dependencies.filter((dependency) => dependency.type === 'required').map((dependency) => dependency.project_id || dependency.version_id).filter(Boolean); const request = confirm.updateFilename ? http.post(`/api/client/servers/${uuid}/plugins/${encodeURIComponent(confirm.updateFilename)}/update`, { project_id: confirm.project.id, dependencies }) : http.post(`/api/client/servers/${uuid}/plugins/projects/${confirm.project.id}/install`, { dependencies }); request.then(() => { setConfirm(undefined); scanInstalled(); discover(query.trim()); }).catch(clearAndAddHttpError); };
    const toggle = (plugin: Installed) => http.post(`/api/client/servers/${uuid}/plugins/${encodeURIComponent(plugin.filename)}/toggle`, { enable: plugin.disabled }).then(scanInstalled).catch(clearAndAddHttpError);
    const remove = (plugin: Installed) => { if (window.confirm(`Remove ${plugin.filename}? Plugin data and configuration will remain.`)) http.delete(`/api/client/servers/${uuid}/plugins/${encodeURIComponent(plugin.filename)}`).then(scanInstalled).catch(clearAndAddHttpError); };

    return <ServerContentBlock title={'Plugins'} showFlashKey={'server:plugins'}>
        <p css={tw`mb-5 text-sm text-neutral-300`}>Discover Modrinth plugins and manage the actual JAR files in this server&apos;s plugins directory. Changes require a server restart.</p>
        <div css={tw`mb-6 flex gap-3 border-b border-neutral-700`}><button className={`border-b-2 px-3 py-2 text-sm font-medium ${tab === 'discover' ? 'border-blue-500 text-neutral-100' : 'border-transparent text-neutral-400'}`} onClick={() => setTab('discover')}>Discover</button><button className={`border-b-2 px-3 py-2 text-sm font-medium ${tab === 'installed' ? 'border-blue-500 text-neutral-100' : 'border-transparent text-neutral-400'}`} onClick={() => setTab('installed')}>Installed</button></div>
        {!context ? <Spinner size={'large'} centered /> : !context.supported ? <div css={tw`rounded border border-yellow-700 bg-neutral-800 p-4 text-sm text-yellow-200`}>Plugin Manager currently supports Bukkit-family servers only (Paper, Purpur, Spigot, Bukkit, and Folia).</div> : !context.version ? <div css={tw`rounded border border-yellow-700 bg-neutral-800 p-4 text-sm text-yellow-200`}>Fluid could not determine this server&apos;s Minecraft version from its runtime log, so it cannot safely install a plugin.</div> : tab === 'discover' ? <>
            <div css={tw`mb-6 flex flex-col gap-3 sm:flex-row`}><input css={tw`flex-1 rounded border border-neutral-600 bg-neutral-900 px-3 py-2 text-neutral-100`} value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && discover(query.trim())} placeholder={'Search Bukkit, Paper, Purpur, Spigot, or Folia plugins'} /><Button color={'primary'} onClick={() => discover(query.trim())}>Search</Button></div>
            {searching ? <Spinner size={'large'} centered /> : <div css={tw`space-y-3`}>{projects.map((project) => <div key={project.id} css={tw`flex flex-col gap-4 rounded-lg border border-neutral-700 bg-neutral-800 p-4 sm:flex-row`}><div css={tw`flex h-12 w-12 flex-shrink-0 items-center justify-center rounded bg-neutral-700 text-lg font-bold text-neutral-300`}>{project.icon ? <img src={project.icon} alt={''} css={tw`h-12 w-12 rounded object-cover`} /> : project.name.slice(0, 1)}</div><div css={tw`min-w-0 flex-1`}><p css={tw`font-semibold text-neutral-100`}>{project.name} <span css={tw`text-xs font-normal text-neutral-400`}>by {project.author}</span></p><p css={tw`mt-1 text-sm text-neutral-300`}>{project.description}</p><p css={tw`mt-2 text-xs text-neutral-400`}>{project.compatible ? `Compatible with ${context.platform} ${context.version}${project.version ? ` - ${project.version.version_number}` : ''}` : project.reason}</p></div><div css={tw`flex flex-shrink-0 items-center gap-2 self-start sm:self-center`}><a css={tw`inline-flex h-9 items-center rounded border border-neutral-600 bg-neutral-700 px-3 text-xs font-semibold text-neutral-50 no-underline transition-colors hover:bg-neutral-600`} href={`/api/client/servers/${uuid}/plugins/projects/${project.id}/download`} target={'_blank'} rel={'noreferrer'}>Download</a><Button size={'xsmall'} color={'primary'} disabled={!project.compatible} onClick={() => installPrompt(project)}>Install</Button></div></div>)}{!!query.trim() && !projects.length && <p css={tw`py-8 text-center text-sm text-neutral-400`}>No compatible server plugins found.</p>}{!query.trim() && <p css={tw`py-8 text-center text-sm text-neutral-400`}>Search for a plugin to see compatible Bukkit-family results.</p>}</div>}
        </> : <>
            {!installed ? <Spinner size={'large'} centered /> : <div css={tw`space-y-3`}>{installed.map((plugin) => <div key={plugin.filename} className={`flex flex-col justify-between gap-3 rounded-lg border border-neutral-700 bg-neutral-800 p-4 sm:flex-row sm:items-center ${plugin.disabled ? 'opacity-55' : ''}`}><div><p css={tw`font-semibold text-neutral-100`}>{plugin.name}</p><p css={tw`mt-1 text-xs text-neutral-400`}>{plugin.filename} - {plugin.status}{plugin.update_available ? ' - update available' : ''}</p></div><div css={tw`flex flex-wrap gap-2`}><Button size={'xsmall'} color={'grey'} onClick={() => toggle(plugin)}>{plugin.disabled ? 'Enable' : 'Disable'}</Button>{plugin.update_available && plugin.project_id && <Button size={'xsmall'} color={'primary'} onClick={() => installPrompt({ id: plugin.project_id!, name: plugin.name, author: '', description: '', downloads: 0, platforms: [], compatible: true }, plugin.filename)}>Update</Button>}<Button size={'xsmall'} color={'red'} onClick={() => remove(plugin)}>Remove</Button></div></div>)}{!installed.length && <p css={tw`text-sm text-neutral-400`}>No plugin JAR files were found in /plugins.</p>}</div>}
        </>}
        {confirm && <div css={tw`fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-60 p-4`}><div css={tw`w-full max-w-lg rounded-lg border border-neutral-600 bg-neutral-900 p-6 shadow-xl`}><h2 css={tw`text-lg font-semibold text-neutral-100`}>{confirm.updateFilename ? 'Update' : 'Install'} {confirm.project.name}</h2><p css={tw`mt-2 text-sm text-neutral-300`}>Required dependencies will be installed together. Optional dependencies are never installed automatically.</p><div css={tw`mt-4 space-y-2 text-sm text-neutral-300`}>{confirm.dependencies.length ? confirm.dependencies.map((dependency, index) => <p key={index}>{dependency.type}: {dependency.project_id || dependency.version_id}{dependency.type === 'incompatible' ? ' (installation will be blocked if installed)' : ''}</p>) : <p>No Modrinth dependencies declared.</p>}</div><p css={tw`mt-4 text-xs text-yellow-200`}>The plugin files are hash-verified before being written. Restart the server yourself after this change.</p><div css={tw`mt-5 flex justify-end gap-3`}><Button color={'grey'} onClick={() => setConfirm(undefined)}>Cancel</Button><Button color={'primary'} onClick={install}>Confirm {confirm.updateFilename ? 'update' : 'install'}</Button></div></div></div>}
    </ServerContentBlock>;
};
