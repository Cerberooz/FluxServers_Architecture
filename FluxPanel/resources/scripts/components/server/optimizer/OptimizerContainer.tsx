import React, { useEffect, useState } from 'react';
import tw from 'twin.macro';
import http from '@/api/http';
import Button from '@/components/elements/Button';
import Modal from '@/components/elements/Modal';
import Spinner from '@/components/elements/Spinner';
import ServerContentBlock from '@/components/elements/ServerContentBlock';
import { ServerContext } from '@/state/server';
import { useFlashKey } from '@/plugins/useFlash';

type Finding = { id: number; severity: string; title: string; explanation: string; impact?: string; gameplay_change: boolean; restart_required: boolean; source?: string; evidence?: { observed?: string; file?: string; key?: string }; recommendation?: { file?: string; key?: string; value?: string | number }; ignored: boolean };
type Network = { ingress_bytes?: number; egress_bytes?: number; ingress_bytes_per_second?: number; egress_bytes_per_second?: number };
type Summary = { implementation?: string; minecraft_version?: string; memory_mb?: number; cpu_percent?: number; spark?: { available: boolean; built_in: boolean }; message?: string; report_id?: string; tps?: number; mspt_p95?: number; network?: Network; server_health?: { score?: number; status?: string }; analysis?: { normal?: boolean; conclusion?: string; message?: string; signals?: string[] }; plugin_usage?: { source: string; percent: number }[] };
type Run = { id: number; type: string; status: string; automatic: boolean; flagged_at?: string; read_at?: string; created_at?: string; summary?: Summary; findings: Finding[] };
type Pagination = { current_page: number; total_pages: number; total: number; per_page: number };
type Response = { data: Run[]; meta: { pagination: Pagination; unread: number } };

const severityClass = (value: string) => value === 'critical' || value === 'high' ? 'text-red-400' : value === 'medium' ? 'text-yellow-300' : 'text-blue-300';
const title = (run: Run) => run.type.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
const rate = (value?: number) => value === undefined ? '-' : `${(value / 1024 / 1024).toFixed(2)} MiB/s`;
const healthLabel = (health?: Summary['server_health']) => {
    if (!health?.status) return 'Awaiting analysis';
    return ({ very_healthy: 'Very Healthy', healthy: 'Healthy', caution: 'Caution', poor: 'Poor', critical: 'Critical' } as Record<string, string>)[health.status] || health.status;
};
const healthColor = (health?: Summary['server_health']) => health?.status === 'very_healthy' || health?.status === 'healthy' ? 'text-green-400' : health?.status === 'caution' ? 'text-yellow-300' : 'text-red-400';

export default () => {
    const uuid = ServerContext.useStoreState((state) => state.server.data!.uuid);
    const { clearAndAddHttpError } = useFlashKey('server:optimizer');
    const [response, setResponse] = useState<Response>();
    const [selectedId, setSelectedId] = useState<number>();
    const [detailsOpen, setDetailsOpen] = useState(false);
    const [reportUrl, setReportUrl] = useState('');
    const [changeNotice, setChangeNotice] = useState<string>();

    const load = (page = response?.meta.pagination.current_page || 1) => http.get(`/api/client/servers/${uuid}/optimizer`, { params: { page } }).then(({ data }) => {
        setResponse(data);
        setSelectedId((current) => data.data.some((run: Run) => run.id === current) ? current : data.data[0]?.id);
    });

    useEffect(() => { load(1).catch(clearAndAddHttpError); }, []);

    const action = (path: string, body?: object) => http.post(`/api/client/servers/${uuid}/optimizer/${path}`, body).then(() => load()).catch(clearAndAddHttpError);
    const importReport = () => http.post(`/api/client/servers/${uuid}/optimizer/import`, { url: reportUrl }).then(() => { setReportUrl(''); return load(1); }).catch(clearAndAddHttpError);
    const selectRun = (run: Run) => {
        setSelectedId(run.id);
        setDetailsOpen(true);
        if (run.automatic && run.flagged_at && !run.read_at) {
            http.post(`/api/client/servers/${uuid}/optimizer/runs/${run.id}/read`).then(() => load()).catch(clearAndAddHttpError);
        }
    };
    const applyRecommendation = (finding: Finding) => http.post(`/api/client/servers/${uuid}/optimizer/findings/${finding.id}/apply`).then(() => {
        const recommendation = finding.recommendation!;
        setChangeNotice(`${recommendation.file}: ${recommendation.key} was changed to ${recommendation.value}. Restart the server for this change to take effect.`);
        return load();
    }).catch(clearAndAddHttpError);

    const runs = response?.data || [];
    const selected = runs.find((run) => run.id === selectedId) || runs[0];
    const scan = runs.find((run) => run.type === 'configuration_scan');
    const scanSummary = scan?.summary;
    const findings = selected?.findings.filter((finding) => !finding.ignored) || [];
    // Reports created before the health-summary upgrade remain useful: derive a
    // conservative conclusion from their stored findings instead of presenting
    // an empty report to the customer.
    const health = selected?.summary?.server_health || (selected?.status === 'completed'
        ? (findings.some((finding) => ['critical', 'high'].includes(finding.severity))
            ? { score: 45, status: 'poor' }
            : findings.some((finding) => finding.severity === 'medium')
            ? { score: 65, status: 'caution' }
            : { score: 100, status: 'very_healthy' })
        : undefined);
    const analysis = selected?.summary?.analysis || (selected?.status === 'completed'
        ? { normal: findings.length === 0, conclusion: healthLabel(health), message: findings.length ? 'This legacy report contains findings that should be reviewed.' : 'This report completed normally. No active performance concerns were found.' }
        : undefined);

    return <ServerContentBlock title={'Optimizer'} showFlashKey={'server:optimizer'}>
        {!response ? <Spinner size={'large'} centered /> : <>
            <p css={tw`mb-6 text-sm text-neutral-300`}>Fluid monitors resource pressure, collects official Spark reports automatically, and turns them into evidence-backed health and plugin usage findings.</p>
            {changeNotice && <div css={tw`mb-6 flex items-start justify-between gap-4 rounded-lg border border-blue-600 bg-blue-900 bg-opacity-30 p-4 text-sm text-blue-100`}><span><strong>Configuration change applied.</strong> {changeNotice}</span><button type={'button'} css={tw`text-blue-200 hover:text-white`} onClick={() => setChangeNotice(undefined)} aria-label={'Dismiss notification'}>×</button></div>}
            <div css={tw`mb-6 grid gap-3 md:grid-cols-4`}>
                <Stat label={'Configuration Health'} value={scan ? `${scan.findings.filter((finding) => !finding.ignored).length} findings` : 'Not scanned'} />
                <Stat label={'Server Health'} value={selected?.status === 'running' ? 'Analysis running' : health?.score !== undefined ? `${healthLabel(health)} · ${health.score}/100` : 'Awaiting report'} />
                <Stat label={'Implementation'} value={selected?.summary?.implementation || scanSummary?.implementation || 'Unknown'} />
                <Stat label={'Spark'} value={scanSummary?.spark?.available ? (scanSummary.spark.built_in ? 'Built in' : 'Installed') : 'Not detected'} />
            </div>
            <div css={tw`mb-8 flex flex-wrap gap-3`}>
                <Button color={'primary'} onClick={() => action('scan')}>Scan Configuration</Button>
                <Button color={'grey'} onClick={() => action('profile', { mode: 'general' })}>Run Performance Analysis</Button>
                <Button color={'grey'} onClick={() => action('profile', { mode: 'lag_spikes' })}>Run Lag Spike Analysis</Button>
                <Button color={'grey'} onClick={() => action('profile', { mode: 'memory' })}>Run Memory Analysis</Button>
            </div>
            <div css={tw`mb-8 rounded-lg border border-neutral-700 bg-neutral-800 p-4`}>
                <p css={tw`font-medium text-neutral-100`}>Automatic Spark collection</p>
                <p css={tw`mt-1 text-sm text-neutral-400`}>Fluid takes a lightweight Spark health sample every 15 minutes. CPU, memory, and network pressure must persist for three samples before a deeper scan is queued, unless an emergency threshold is reached. It reads the official URL from the server log; you can still import a report manually.</p>
                <div css={tw`mt-3 flex flex-col gap-3 sm:flex-row`}>
                    <input css={tw`flex-1 rounded border border-neutral-600 bg-neutral-900 px-3 py-2 text-neutral-100`} value={reportUrl} onChange={(event) => setReportUrl(event.target.value)} placeholder={'https://spark.lucko.me/abc123'} />
                    <Button color={'primary'} disabled={!reportUrl} onClick={importReport}>Import report</Button>
                </div>
            </div>
            <section css={tw`mb-8`}>
                <div css={tw`mb-3 flex items-center justify-between`}>
                    <h2 css={tw`text-lg font-semibold text-neutral-100`}>Performance reports</h2>
                    <span css={tw`text-xs text-neutral-400`}>{response.meta.pagination.total} total{response.meta.unread ? ` · ${response.meta.unread} unread alert${response.meta.unread === 1 ? '' : 's'}` : ''}</span>
                </div>
                <div css={tw`overflow-hidden rounded-lg border border-neutral-700 bg-neutral-800`}>
                    {runs.length ? runs.map((run) => <button key={run.id} type={'button'} onClick={() => selectRun(run)} css={tw`flex w-full items-center gap-3 border-b border-neutral-700 px-4 py-3 text-left last:border-b-0 hover:bg-neutral-700`}>
                        <span css={tw`h-2 w-2 flex-shrink-0 rounded-full bg-transparent`}>{run.automatic && run.flagged_at && !run.read_at && <span css={tw`block h-2 w-2 rounded-full bg-red-500`} />}</span>
                        <span css={tw`min-w-0 flex-1`}><span css={tw`block truncate text-sm font-medium text-neutral-100`}>{title(run)}</span><span css={tw`block truncate text-xs text-neutral-400`}>{run.automatic ? 'Automatic alert' : 'Manual run'} · {run.status}</span></span>
                        <span css={tw`text-xs text-neutral-400`}>{run.created_at ? new Date(run.created_at).toLocaleDateString() : ''}</span>
                    </button>) : <p css={tw`px-4 py-5 text-sm text-neutral-400`}>No optimizer reports yet.</p>}
                </div>
                {response.meta.pagination.total_pages > 1 && <div css={tw`mt-3 flex items-center justify-end gap-3`}>
                    <Button size={'xsmall'} color={'grey'} disabled={response.meta.pagination.current_page <= 1} onClick={() => load(response.meta.pagination.current_page - 1)}>Previous</Button>
                    <span css={tw`text-xs text-neutral-400`}>Page {response.meta.pagination.current_page} of {response.meta.pagination.total_pages}</span>
                    <Button size={'xsmall'} color={'grey'} disabled={response.meta.pagination.current_page >= response.meta.pagination.total_pages} onClick={() => load(response.meta.pagination.current_page + 1)}>Next</Button>
                </div>}
            </section>
            {selected && <Modal visible={detailsOpen} onDismissed={() => setDetailsOpen(false)}>
                <section css={tw`space-y-4`}>
                <div css={tw`flex flex-wrap items-center justify-between gap-3`}>
                    <div><h2 css={tw`text-lg font-semibold text-neutral-100`}>{title(selected)}</h2><p css={tw`mt-1 text-sm text-neutral-400`}>{selected.summary?.message || 'Completed optimizer report.'}</p></div>
                    {selected.summary?.report_id && <a css={tw`text-sm text-blue-300 hover:text-blue-200`} href={`https://spark.lucko.me/${selected.summary.report_id}`} target={'_blank'} rel={'noreferrer'}>Open Spark report</a>}
                </div>
                {selected.status === 'running' ? <div css={tw`rounded-lg border border-blue-700 bg-blue-900 bg-opacity-20 p-4 text-sm text-blue-100`}>Analysis is in progress. Fluid will show the health conclusion, ranked plugin usage, network evidence, and findings after Spark publishes its report.</div> : <div css={tw`rounded-lg border border-neutral-700 bg-neutral-800 p-4`}><div css={tw`flex flex-wrap items-baseline justify-between gap-2`}><div><p css={tw`text-xs font-medium uppercase tracking-wide text-neutral-400`}>Health of this server</p><p className={healthColor(health)} css={tw`mt-1 text-xl font-semibold`}>{analysis?.conclusion || healthLabel(health)}</p></div>{health?.score !== undefined && <span css={tw`text-sm font-semibold text-neutral-100`}>{health.score}/100</span>}</div><p css={tw`mt-3 text-sm text-neutral-300`}>{analysis?.message || (findings.length ? 'This report contains findings that should be reviewed.' : 'This report completed normally. No active performance concerns were found.')}</p>{analysis?.signals?.length ? <ul css={tw`mt-3 list-disc space-y-1 pl-5 text-sm text-neutral-400`}>{analysis.signals.map((signal) => <li key={signal}>{signal}</li>)}</ul> : null}</div>}
                <div css={tw`grid gap-3 md:grid-cols-3`}>
                    <Stat label={'TPS / MSPT P95'} value={selected.summary?.tps !== undefined ? `${selected.summary.tps} / ${selected.summary.mspt_p95 ?? '-'}ms` : '-'} />
                    <Stat label={'Network ingress'} value={rate(selected.summary?.network?.ingress_bytes_per_second)} />
                    <Stat label={'Network egress'} value={rate(selected.summary?.network?.egress_bytes_per_second)} />
                </div>
                {!!selected.summary?.plugin_usage?.length && <div css={tw`rounded-lg border border-neutral-700 bg-neutral-800 p-4`}><h3 css={tw`font-medium text-neutral-100`}>Plugin resource usage</h3><div css={tw`mt-3 space-y-2`}>{selected.summary.plugin_usage.map((plugin, index) => <div key={`${plugin.source}-${index}`} css={tw`flex justify-between text-sm`}><span css={tw`text-neutral-300`}>{index + 1}. {plugin.source}</span><span css={tw`font-medium text-neutral-100`}>{plugin.percent.toFixed(1)}%</span></div>)}</div></div>}
                {findings.map((finding) => <div key={finding.id} css={tw`rounded-lg border border-neutral-700 bg-neutral-800 p-4`}>
                    <div css={tw`flex flex-col justify-between gap-3 sm:flex-row`}><div><p css={tw`font-semibold text-neutral-100`}>{finding.title} <span className={severityClass(finding.severity)}>{finding.severity.toUpperCase()}</span></p><p css={tw`mt-2 text-sm text-neutral-300`}>{finding.explanation}</p><p css={tw`mt-2 text-xs text-neutral-400`}>{finding.evidence?.key ? `Observed: ${finding.evidence.key} = ${finding.evidence.observed}` : 'Evidence collected from Spark and Wings resource counters.'}{` | Impact: ${finding.impact || 'unknown'}${finding.restart_required ? ' | Restart required' : ''}`}</p>{finding.recommendation?.file && <p css={tw`mt-2 text-sm text-blue-200`}>Recommended: {finding.recommendation.file} — {finding.recommendation.key} = {finding.recommendation.value}</p>}{finding.source && <a css={tw`mt-2 inline-block text-xs text-blue-300 hover:text-blue-200`} href={finding.source} target={'_blank'} rel={'noreferrer'}>Authoritative reference</a>}</div><div css={tw`flex h-auto flex-wrap gap-2`}><Button size={'xsmall'} color={'grey'} onClick={() => action(`findings/${finding.id}/ignore`)}>Ignore</Button>{finding.recommendation?.file && !finding.gameplay_change && <Button size={'xsmall'} color={'primary'} onClick={() => applyRecommendation(finding)}>Apply recommended setting</Button>}</div></div>
                </div>)}
                {!findings.length && <div css={tw`rounded-lg border border-neutral-700 bg-neutral-800 p-4 text-sm text-neutral-400`}>This report has no active findings.</div>}
                </section>
            </Modal>}
        </>}
    </ServerContentBlock>;
};

const Stat = ({ label, value }: { label: string; value: string }) => <div css={tw`rounded-lg border border-neutral-700 bg-neutral-800 p-4`}><p css={tw`text-xs font-medium uppercase tracking-wide text-neutral-400`}>{label}</p><p css={tw`mt-2 truncate text-sm font-semibold text-neutral-100`}>{value}</p></div>;
