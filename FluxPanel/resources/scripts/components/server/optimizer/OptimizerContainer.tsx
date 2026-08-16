import React, { useEffect, useMemo, useState } from 'react';
import tw from 'twin.macro';
import http from '@/api/http';
import Button from '@/components/elements/Button';
import Modal from '@/components/elements/Modal';
import Spinner from '@/components/elements/Spinner';
import Switch from '@/components/elements/Switch';
import ServerContentBlock from '@/components/elements/ServerContentBlock';
import { ServerContext } from '@/state/server';
import { useFlashKey } from '@/plugins/useFlash';

type RecommendationOption = { label: string; value: string | number | boolean };
type Finding = {
    id: number;
    severity: string;
    title: string;
    explanation: string;
    gameplay_change: boolean;
    restart_required: boolean;
    evidence?: { observed?: string; file?: string; key?: string };
    recommendation?: { file?: string; key?: string; value?: string | number | boolean; options?: RecommendationOption[] };
    ignored: boolean;
};
type NetworkSample = { captured_at: string; ingress_bytes_per_second?: number; egress_bytes_per_second?: number };
type Network = {
    ingress_bytes_per_second?: number;
    egress_bytes_per_second?: number;
    samples?: NetworkSample[];
};
type Summary = {
    report_id?: string;
    message?: string;
    network?: Network;
    plugin_usage?: { source: string; percent: number }[];
    server_health?: { score?: number; status?: string };
    analysis?: { normal?: boolean; conclusion?: string; message?: string; signals?: string[] };
};
type Run = {
    id: number;
    type: string;
    status: string;
    automatic: boolean;
    flagged_at?: string;
    read_at?: string;
    created_at?: string;
    completed_at?: string;
    error?: string;
    summary?: Summary;
    findings: Finding[];
};
type Pagination = { current_page: number; total_pages: number; total: number; per_page: number };
type Response = {
    data: Run[];
    configuration?: Run;
    settings: { automatic_analysis: boolean };
    meta: { pagination: Pagination; unread: number };
};

const healthName = (status?: string) => ({
    very_healthy: 'Very healthy',
    healthy: 'Healthy',
    caution: 'Caution',
    poor: 'Poor',
    critical: 'Critical',
}[status || ''] || 'Normal');

const healthClass = (status?: string) => status === 'critical' || status === 'poor'
    ? 'text-red-400'
    : status === 'caution'
        ? 'text-yellow-300'
        : 'text-green-400';

const rate = (value?: number) => value === undefined ? 'Not sampled' : `${(value / 1024 / 1024).toFixed(2)} MiB/s`;
const formattedDate = (value?: string) => value ? new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—';
const reportTitle = (run: Run) => run.summary?.report_id
    ? `Spark report · ${run.summary.report_id}`
    : run.automatic
        ? 'Automatic analysis'
        : 'Manual scan';
const reportSource = (run: Run) => run.type === 'spark_import'
    ? 'Imported link'
    : run.automatic
        ? 'Performance degradation'
        : 'Live server scan';
const reportResult = (run: Run) => {
    if (run.status === 'running' || run.status === 'queued') return 'Collecting profile data…';
    if (run.status === 'failed') return 'Analysis failed';
    const plugins = run.summary?.plugin_usage?.length || 0;
    const network = run.summary?.network;
    const highNetwork = Math.max(network?.ingress_bytes_per_second || 0, network?.egress_bytes_per_second || 0) >= 20 * 1024 * 1024;
    if (!plugins && !highNetwork) return run.summary?.analysis?.normal ? 'No issues found' : healthName(run.summary?.server_health?.status);
    return `${plugins ? `${plugins} plugin ${plugins === 1 ? 'issue' : 'issues'}` : 'No plugin issues'} · ${highNetwork ? 'High network' : 'Network normal'}`;
};

export default () => {
    const uuid = ServerContext.useStoreState((state) => state.server.data!.uuid);
    const { clearAndAddHttpError } = useFlashKey('server:optimizer');
    const [tab, setTab] = useState<'configuration' | 'spark'>('configuration');
    const [response, setResponse] = useState<Response>();
    const [selected, setSelected] = useState<Run>();
    const [reportUrl, setReportUrl] = useState('');
    const [changeNotice, setChangeNotice] = useState<string>();

    const load = (page = response?.meta.pagination.current_page || 1) => http
        .get(`/api/client/servers/${uuid}/optimizer`, { params: { page } })
        .then(({ data }) => setResponse(data));

    useEffect(() => { load(1).catch(clearAndAddHttpError); }, []);

    const scanConfiguration = () => http.post(`/api/client/servers/${uuid}/optimizer/scan`)
        .then(() => load(1))
        .catch(clearAndAddHttpError);
    const startScan = () => http.post(`/api/client/servers/${uuid}/optimizer/profile`, { mode: 'general' })
        .then(() => { setTab('spark'); return load(1); })
        .catch(clearAndAddHttpError);
    const importReport = () => http.post(`/api/client/servers/${uuid}/optimizer/import`, { url: reportUrl })
        .then(() => { setReportUrl(''); setTab('spark'); return load(1); })
        .catch(clearAndAddHttpError);
    const setAutomaticAnalysis = (enabled: boolean) => http.post(`/api/client/servers/${uuid}/optimizer/settings`, { automatic_analysis: enabled })
        .then(() => load())
        .catch(clearAndAddHttpError);
    const apply = (finding: Finding, value?: RecommendationOption['value']) => http.post(
        `/api/client/servers/${uuid}/optimizer/findings/${finding.id}/apply`,
        value === undefined ? undefined : { value },
    ).then(() => {
        const recommendation = finding.recommendation!;
        setChangeNotice(`${recommendation.file}: ${recommendation.key} was updated to ${value ?? recommendation.value}. Restart the server for the change to take effect.`);
        return load(1);
    }).catch(clearAndAddHttpError);
    const openReport = (run: Run) => {
        setSelected(run);
        if (run.automatic && run.flagged_at && !run.read_at) {
            http.post(`/api/client/servers/${uuid}/optimizer/runs/${run.id}/read`)
                .then(() => load())
                .catch(clearAndAddHttpError);
        }
    };

    const configurationFindings = response?.configuration?.findings.filter((finding) => !finding.ignored && finding.recommendation?.file) || [];

    return <ServerContentBlock title={'Optimizer'} showFlashKey={'server:optimizer'}>
        {!response ? <Spinner size={'large'} centered /> : <>
            <div css={tw`mb-6 border-b border-neutral-700 pb-5`}>
                <h2 css={tw`text-lg font-semibold text-neutral-100`}>Optimizer</h2>
                <p css={tw`mt-1 text-sm text-neutral-400`}>Tune server configuration or analyse Spark reports.</p>
            </div>

            <div css={tw`mb-6 flex gap-7 border-b border-neutral-700`}>
                <TabButton active={tab === 'configuration'} onClick={() => setTab('configuration')}>Configuration Optimizer</TabButton>
                <TabButton active={tab === 'spark'} onClick={() => setTab('spark')}>Spark Analyser</TabButton>
            </div>

            {changeNotice && <div css={tw`mb-5 flex items-start justify-between gap-4 border border-blue-700 bg-blue-900 bg-opacity-20 p-4 text-sm text-blue-100`}>
                <span><strong>Configuration changed.</strong> {changeNotice}</span>
                <button type={'button'} css={tw`text-blue-200 hover:text-white`} onClick={() => setChangeNotice(undefined)} aria-label={'Dismiss notification'}>×</button>
            </div>}

            {tab === 'configuration'
                ? <ConfigurationOptimizer findings={configurationFindings} scannedAt={response.configuration?.completed_at} onScan={scanConfiguration} onApply={apply} />
                : <SparkAnalyser
                    runs={response.data}
                    pagination={response.meta.pagination}
                    unread={response.meta.unread}
                    automatic={response.settings.automatic_analysis}
                    reportUrl={reportUrl}
                    onReportUrl={setReportUrl}
                    onStart={startScan}
                    onImport={importReport}
                    onAutomaticChange={setAutomaticAnalysis}
                    onOpen={openReport}
                    onPage={load}
                />}

            {selected && <ReportModal run={selected} onClose={() => setSelected(undefined)} />}
        </>}
    </ServerContentBlock>;
};

const TabButton = ({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) => <button
    type={'button'}
    onClick={onClick}
    css={tw`-mb-px border-b-2 border-transparent px-0 pb-3 text-sm font-medium text-neutral-400 transition-colors hover:text-neutral-200`}
    className={active ? 'border-blue-500 text-neutral-100' : ''}
>{children}</button>;

const ConfigurationOptimizer = ({ findings, scannedAt, onScan, onApply }: {
    findings: Finding[];
    scannedAt?: string;
    onScan: () => void;
    onApply: (finding: Finding, value?: RecommendationOption['value']) => void;
}) => <section>
    <div css={tw`mb-5 flex flex-wrap items-end justify-between gap-4`}>
        <div>
            <h3 css={tw`text-base font-semibold text-neutral-100`}>Configuration Optimizer</h3>
            <p css={tw`mt-1 text-sm text-neutral-400`}>Review performance-impacting settings and choose a value to update it directly.</p>
        </div>
        <div css={tw`flex items-center gap-4`}>
            {scannedAt && <span css={tw`text-xs text-neutral-500`}>Last scanned {formattedDate(scannedAt)}</span>}
            <Button size={'xsmall'} color={'primary'} onClick={onScan}>Scan configuration</Button>
        </div>
    </div>
    {findings.length
        ? <div css={tw`grid gap-4 lg:grid-cols-2`}>
            {findings.map((finding) => <ConfigurationCard key={finding.id} finding={finding} onApply={onApply} />)}
        </div>
        : <div css={tw`border border-neutral-700 bg-neutral-800 p-6 text-sm text-neutral-400`}>
            No concerning configuration settings are available yet. Run a configuration scan to inspect this server&apos;s supported Minecraft files.
        </div>}
</section>;

const ConfigurationCard = ({ finding, onApply }: { finding: Finding; onApply: (finding: Finding, value?: RecommendationOption['value']) => void }) => {
    const recommendation = finding.recommendation!;
    const options = recommendation.options || [];

    return <article css={tw`border border-neutral-700 bg-neutral-800`}>
        <div css={tw`flex items-start justify-between gap-4 border-b border-neutral-700 px-4 py-3`}>
            <div css={tw`min-w-0`}>
                <h4 css={tw`text-sm font-semibold text-neutral-100`}>{finding.title}</h4>
                <p css={tw`mt-1 truncate text-xs text-neutral-500`}>{recommendation.file} · {recommendation.key}</p>
            </div>
            <span css={tw`flex-shrink-0 text-xs text-neutral-400`}>Current: {finding.evidence?.observed ?? '—'}</span>
        </div>
        <div css={tw`px-4 py-3`}>
            <p css={tw`h-10 text-sm leading-5 text-neutral-300`}>{finding.explanation}</p>
            {options.length
                ? <div css={tw`mt-4 grid grid-cols-3 gap-2`}>
                    {options.map((option, index) => <button
                        key={option.label}
                        type={'button'}
                        onClick={() => onApply(finding, option.value)}
                        css={tw`flex items-center justify-between border border-neutral-700 bg-neutral-900 px-3 py-2 text-left text-xs text-neutral-300 transition-colors hover:border-blue-500 hover:text-white`}
                        className={index === 1 ? 'border-blue-500 bg-blue-600 text-white' : ''}
                    ><span css={tw`uppercase tracking-wide`}>{option.label.split(':')[0]}</span><strong>{String(option.value)}</strong></button>)}
                </div>
                : <div css={tw`mt-4 flex items-center justify-between gap-3`}>
                    <span css={tw`text-xs text-neutral-400`}>Recommended: {String(recommendation.value)}</span>
                    <Button size={'xsmall'} color={'primary'} onClick={() => onApply(finding)}>Apply</Button>
                </div>}
            {finding.restart_required && <p css={tw`mt-3 text-xs text-yellow-200`}>A server restart is required after this change.</p>}
        </div>
    </article>;
};

const SparkAnalyser = ({ runs, pagination, unread, automatic, reportUrl, onReportUrl, onStart, onImport, onAutomaticChange, onOpen, onPage }: {
    runs: Run[];
    pagination: Pagination;
    unread: number;
    automatic: boolean;
    reportUrl: string;
    onReportUrl: (value: string) => void;
    onStart: () => void;
    onImport: () => void;
    onAutomaticChange: (enabled: boolean) => void;
    onOpen: (run: Run) => void;
    onPage: (page: number) => void;
}) => <section>
    <div css={tw`mb-5 flex flex-col justify-between gap-4 border-b border-neutral-700 pb-5 lg:flex-row lg:items-center`}>
        <div>
            <h3 css={tw`text-base font-semibold text-neutral-100`}>Spark Analyser</h3>
            <p css={tw`mt-1 text-sm text-neutral-400`}>Run a short server profile or analyse an existing Spark report.</p>
        </div>
        <Switch key={automatic ? 'automatic-on' : 'automatic-off'} name={'optimizer-auto-analysis'} defaultChecked={automatic} onChange={(event) => onAutomaticChange(event.currentTarget.checked)} label={'Automatic analysis'} description={'Run only after sustained degradation or an emergency threshold.'} />
    </div>

    <div css={tw`mb-8 border-b border-neutral-700 pb-5`}>
        <div css={tw`grid gap-5 lg:grid-cols-3 lg:items-end`}>
            <div>
                <h4 css={tw`text-sm font-semibold text-neutral-100`}>Manual scan</h4>
                <p css={tw`mt-1 text-xs text-neutral-400`}>Run a 60 second profile from this server.</p>
                <div css={tw`mt-3`}><Button size={'xsmall'} color={'primary'} onClick={onStart}>Start scan</Button></div>
            </div>
            <p css={tw`pb-2 text-sm text-neutral-500`}>or analyse an existing Spark report</p>
            <div>
                <h4 css={tw`text-sm font-semibold text-neutral-100`}>Spark report link</h4>
                <p css={tw`mt-1 text-xs text-neutral-400`}>Paste an official spark.lucko.me report link.</p>
                <div css={tw`mt-3 flex gap-2`}>
                    <input css={tw`min-w-0 flex-1 border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100`} value={reportUrl} onChange={(event) => onReportUrl(event.target.value)} placeholder={'https://spark.lucko.me/abc123'} />
                    <Button size={'xsmall'} color={'primary'} disabled={!reportUrl} onClick={onImport}>Analyse</Button>
                </div>
            </div>
        </div>
    </div>

    <div css={tw`mb-3 flex items-end justify-between gap-3`}>
        <div><h3 css={tw`text-base font-semibold text-neutral-100`}>Reports</h3><p css={tw`mt-1 text-sm text-neutral-400`}>Completed and currently processing analyses.</p></div>
        <span css={tw`text-xs text-neutral-500`}>{pagination.total} total{unread ? ` · ${unread} unread alert${unread === 1 ? '' : 's'}` : ''}</span>
    </div>
    <div css={tw`overflow-x-auto border border-neutral-700 bg-neutral-800`}>
        <div css={tw`min-w-full`} style={{ minWidth: '760px' }}>
            <div css={tw`grid grid-cols-12 gap-3 border-b border-neutral-700 px-4 py-3 text-xs font-medium uppercase tracking-wide text-neutral-500`}>
                <span css={tw`col-span-4`}>Report</span><span css={tw`col-span-2`}>Source</span><span css={tw`col-span-3`}>Result</span><span css={tw`col-span-2`}>Status</span><span css={tw`col-span-1`}>Updated</span>
            </div>
            {runs.length ? runs.map((run) => <button key={run.id} type={'button'} onClick={() => onOpen(run)} css={tw`grid w-full grid-cols-12 gap-3 border-b border-neutral-700 px-4 py-4 text-left text-sm transition-colors last:border-b-0 hover:bg-neutral-700`}>
                <span css={tw`col-span-4 flex min-w-0 items-center gap-2 font-semibold text-neutral-100`}><span css={tw`h-2 w-2 flex-shrink-0 rounded-full bg-transparent`}>{run.automatic && run.flagged_at && !run.read_at && <i css={tw`block h-2 w-2 rounded-full bg-red-500`} />}</span><span css={tw`truncate`}>{reportTitle(run)}</span></span>
                <span css={tw`col-span-2 truncate text-neutral-400`}>{reportSource(run)}</span>
                <span css={tw`col-span-3 truncate text-neutral-200`}>{reportResult(run)}</span>
                <span className={run.status === 'failed' ? 'text-red-400' : run.status === 'completed' ? 'text-green-400' : 'text-blue-300'} css={tw`col-span-2 font-semibold uppercase tracking-wide text-xs`}>{run.status}</span>
                <span css={tw`col-span-1 whitespace-nowrap text-xs text-blue-300`}>{run.status === 'completed' ? 'View →' : formattedDate(run.updated_at || run.created_at)}</span>
            </button>) : <p css={tw`px-4 py-6 text-sm text-neutral-400`}>No Spark reports yet.</p>}
        </div>
    </div>
    {pagination.total_pages > 1 && <div css={tw`mt-4 flex items-center justify-between`}>
        <span css={tw`text-xs text-neutral-500`}>Showing {(pagination.current_page - 1) * pagination.per_page + 1}–{Math.min(pagination.current_page * pagination.per_page, pagination.total)} of {pagination.total} reports</span>
        <div css={tw`flex items-center gap-2`}><Button size={'xsmall'} color={'grey'} disabled={pagination.current_page <= 1} onClick={() => onPage(pagination.current_page - 1)}>Previous</Button><span css={tw`text-xs text-neutral-400`}>Page {pagination.current_page} of {pagination.total_pages}</span><Button size={'xsmall'} color={'grey'} disabled={pagination.current_page >= pagination.total_pages} onClick={() => onPage(pagination.current_page + 1)}>Next</Button></div>
    </div>}
</section>;

const ReportModal = ({ run, onClose }: { run: Run; onClose: () => void }) => {
    const analysis = run.summary?.analysis;
    const health = run.summary?.server_health;
    const plugins = run.summary?.plugin_usage || [];
    const samples = run.summary?.network?.samples || [];
    const peak = Math.max(1, ...samples.flatMap((sample) => [sample.ingress_bytes_per_second || 0, sample.egress_bytes_per_second || 0]));
    const networkRate = Math.max(run.summary?.network?.ingress_bytes_per_second || 0, run.summary?.network?.egress_bytes_per_second || 0);
    const networkMessage = networkRate >= 20 * 1024 * 1024
        ? `Traffic was unusually high during this report. Peak observed rate: ${rate(networkRate)}.`
        : samples.length > 1 ? 'Incoming and outgoing traffic stayed within the configured alert threshold during this report.' : 'Network sampling was not available for this report.';

    return <Modal visible onDismissed={onClose}>
        <section css={tw`space-y-6`}>
            <div css={tw`border-b border-neutral-700 pb-4`}>
                <h2 css={tw`text-lg font-semibold text-neutral-100`}>{reportTitle(run)}</h2>
                <p css={tw`mt-1 text-sm text-neutral-400`}>{run.status === 'failed' ? run.error || 'This analysis could not be completed.' : `${reportSource(run)} · ${run.status}`}</p>
            </div>
            {run.status === 'running' || run.status === 'queued'
                ? <div css={tw`border border-blue-700 bg-blue-900 bg-opacity-20 p-4 text-sm text-blue-100`}>Analysis is in progress. Fluid will add the diagnosis, plugin ranking, and network samples after Spark publishes the report.</div>
                : <>
                    <section><h3 css={tw`text-base font-semibold text-neutral-100`}>Diagnosis</h3><p css={tw`mt-1 text-sm text-neutral-400`}>A simple summary of what may be affecting this server.</p>
                        <div css={tw`mt-3 divide-y divide-neutral-700 border border-neutral-700 bg-neutral-900`}>
                            <DiagnosisRow label={'Performance'} value={analysis?.message || 'No performance diagnosis is available for this legacy report.'} state={healthName(health?.status)} stateClass={healthClass(health?.status)} />
                            <DiagnosisRow label={'Network'} value={networkMessage} state={networkRate >= 20 * 1024 * 1024 ? 'Check' : 'Normal'} stateClass={networkRate >= 20 * 1024 * 1024 ? 'text-yellow-300' : 'text-green-400'} />
                        </div>
                    </section>
                    <section><h3 css={tw`text-base font-semibold text-neutral-100`}>Plugin resource usage</h3><p css={tw`mt-1 text-sm text-neutral-400`}>Plugins ranked by their impact during this report.</p>
                        <div css={tw`mt-3 divide-y divide-neutral-700 border border-neutral-700 bg-neutral-900`}>
                            {plugins.length ? plugins.map((plugin, index) => <PluginRow key={`${plugin.source}-${index}`} index={index + 1} source={plugin.source} percent={plugin.percent} />) : <p css={tw`p-4 text-sm text-neutral-400`}>Spark did not attribute sampled server-thread time to a plugin in this report.</p>}
                        </div>
                    </section>
                    <section><div css={tw`flex items-end justify-between gap-3`}><div><h3 css={tw`text-base font-semibold text-neutral-100`}>Network activity</h3><p css={tw`mt-1 text-sm text-neutral-400`}>Ingress and egress captured while this report was generated.</p></div><span css={tw`text-xs text-neutral-500`}>Ingress <i css={tw`mx-1 inline-block h-2 w-2 bg-blue-500`} /> Egress <i css={tw`mx-1 inline-block h-2 w-2 bg-neutral-100`} /></span></div>
                        <div css={tw`mt-3 flex h-32 items-end gap-1 border border-neutral-700 bg-neutral-900 px-3 pb-5 pt-3`}>
                            {samples.length > 1 ? samples.map((sample, index) => <div key={`${sample.captured_at}-${index}`} css={tw`flex h-full min-w-0 flex-1 items-end justify-center gap-px`} title={`${formattedDate(sample.captured_at)} · ingress ${rate(sample.ingress_bytes_per_second)} · egress ${rate(sample.egress_bytes_per_second)}`}><i css={tw`block w-1 bg-blue-500`} style={{ height: `${Math.max(3, ((sample.ingress_bytes_per_second || 0) / peak) * 100)}%` }} /><i css={tw`block w-1 bg-neutral-100`} style={{ height: `${Math.max(3, ((sample.egress_bytes_per_second || 0) / peak) * 100)}%` }} /></div>) : <p css={tw`w-full text-center text-sm text-neutral-500`}>No network samples are available for this report.</p>}
                        </div>
                    </section>
                </>}
            <div css={tw`flex items-center justify-between border-t border-neutral-700 pt-4 text-xs text-neutral-500`}><span>{run.completed_at ? `Report completed ${formattedDate(run.completed_at)}` : 'Report in progress'}</span>{run.summary?.report_id && <a css={tw`font-semibold text-blue-300 hover:text-blue-200`} href={`https://spark.lucko.me/${run.summary.report_id}`} target={'_blank'} rel={'noreferrer'}>Open original Spark report ↗</a>}</div>
        </section>
    </Modal>;
};

const DiagnosisRow = ({ label, value, state, stateClass }: { label: string; value: string; state: string; stateClass: string }) => <div css={tw`flex items-start justify-between gap-4 p-4`}><div><h4 css={tw`text-sm font-semibold text-neutral-100`}>{label}</h4><p css={tw`mt-2 text-sm text-neutral-300`}>{value}</p></div><span className={stateClass} css={tw`flex-shrink-0 text-xs font-semibold`}>{state}</span></div>;

const PluginRow = ({ index, source, percent }: { index: number; source: string; percent: number }) => {
    const color = percent >= 25 ? 'bg-red-400' : percent >= 10 ? 'bg-yellow-300' : 'bg-blue-500';
    const label = percent >= 25 ? 'High' : percent >= 10 ? 'Medium' : 'Low';
    const className = percent >= 25 ? 'text-red-400' : percent >= 10 ? 'text-yellow-300' : 'text-blue-300';

    return <div css={tw`grid grid-cols-12 items-center gap-3 p-3`}><span css={tw`col-span-1 text-sm font-semibold text-neutral-500`}>{index}</span><span css={tw`col-span-3 truncate text-sm font-semibold text-neutral-100`}>{source}</span><span css={tw`col-span-6 h-1.5 overflow-hidden bg-neutral-700`}><i className={color} css={tw`block h-full`} style={{ width: `${Math.min(100, Math.max(2, percent))}%` }} /></span><span className={className} css={tw`col-span-2 text-right text-xs font-semibold`}>{label} · {percent.toFixed(1)}%</span></div>;
};
