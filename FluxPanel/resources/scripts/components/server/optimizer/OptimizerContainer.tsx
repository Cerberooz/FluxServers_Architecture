import React, { useEffect, useState } from 'react';
import tw from 'twin.macro';
import http from '@/api/http';
import Button from '@/components/elements/Button';
import Spinner from '@/components/elements/Spinner';
import ServerContentBlock from '@/components/elements/ServerContentBlock';
import { ServerContext } from '@/state/server';
import { useFlashKey } from '@/plugins/useFlash';

type Finding = { id: number; severity: string; title: string; explanation: string; impact?: string; gameplay_change: boolean; restart_required: boolean; source?: string; evidence?: { observed?: string; file?: string; key?: string }; recommendation?: { file?: string; key?: string; value?: string | number }; ignored: boolean };
type Summary = { implementation?: string; minecraft_version?: string; memory_mb?: number; cpu_percent?: number; spark?: { available: boolean; built_in: boolean }; message?: string; report_id?: string };
type Run = { id: number; type: string; status: string; summary?: Summary; findings: Finding[] };

const severityClass = (value: string) => value === 'critical' || value === 'high' ? 'text-red-400' : value === 'medium' ? 'text-yellow-300' : 'text-blue-300';

export default () => {
    const uuid = ServerContext.useStoreState((state) => state.server.data!.uuid);
    const { clearAndAddHttpError } = useFlashKey('server:optimizer');
    const [runs, setRuns] = useState<Run[]>();
    const [reportUrl, setReportUrl] = useState('');
    const [changeNotice, setChangeNotice] = useState<string>();
    const load = () => http.get(`/api/client/servers/${uuid}/optimizer`).then(({ data }) => setRuns(data.data));
    useEffect(() => { load().catch(clearAndAddHttpError); }, []);
    const action = (path: string, body?: object) => http.post(`/api/client/servers/${uuid}/optimizer/${path}`, body).then(load).catch(clearAndAddHttpError);
    const importReport = () => http.post(`/api/client/servers/${uuid}/optimizer/import`, { url: reportUrl }).then(() => { setReportUrl(''); return load(); }).catch(clearAndAddHttpError);
    const applyRecommendation = (finding: Finding) => http.post(`/api/client/servers/${uuid}/optimizer/findings/${finding.id}/apply`).then(() => {
        const recommendation = finding.recommendation!;
        setChangeNotice(`${recommendation.file}: ${recommendation.key} was changed to ${recommendation.value}. Restart the server for this change to take effect.`);
        return load();
    }).catch(clearAndAddHttpError);
    const scan = runs?.find((run) => run.type === 'configuration_scan');
    const spark = runs?.find((run) => run.type === 'spark_import');
    const findings = [...(scan?.findings || []), ...(spark?.findings || [])];
    const summary = scan?.summary;

    return <ServerContentBlock title={'Optimizer'} showFlashKey={'server:optimizer'}>
        {!runs ? <Spinner size={'large'} centered /> : <>
            <p css={tw`mb-6 text-sm text-neutral-300`}>Evidence-based Minecraft configuration checks and Spark report analysis. Safe changes create a rollback snapshot.</p>
            {changeNotice && <div css={tw`mb-6 flex items-start justify-between gap-4 rounded-lg border border-blue-600 bg-blue-900 bg-opacity-30 p-4 text-sm text-blue-100`}><span><strong>Configuration change applied.</strong> {changeNotice}</span><button type={'button'} css={tw`text-blue-200 hover:text-white`} onClick={() => setChangeNotice(undefined)} aria-label={'Dismiss notification'}>×</button></div>}
            <div css={tw`mb-6 grid gap-3 md:grid-cols-4`}>
                <Stat label={'Configuration Health'} value={scan ? `${scan.findings.filter((finding) => !finding.ignored).length} findings` : 'Not scanned'} />
                <Stat label={'Implementation'} value={summary?.implementation || 'Unknown'} />
                <Stat label={'Memory / CPU'} value={summary ? `${summary.memory_mb} MB / ${summary.cpu_percent || 'Unlimited'}%` : '-'} />
                <Stat label={'Spark'} value={summary?.spark?.available ? (summary.spark.built_in ? 'Built in' : 'Installed') : 'Not detected'} />
            </div>
            <div css={tw`mb-8 flex flex-wrap gap-3`}>
                <Button color={'primary'} onClick={() => action('scan')}>Scan Configuration</Button>
                <Button color={'grey'} onClick={() => action('profile', { mode: 'general' })}>Run Performance Analysis</Button>
                <Button color={'grey'} onClick={() => action('profile', { mode: 'lag_spikes' })}>Run Lag Spike Analysis</Button>
                <Button color={'grey'} onClick={() => action('profile', { mode: 'memory' })}>Run Memory Analysis</Button>
            </div>
            <div css={tw`mb-8 rounded-lg border border-neutral-700 bg-neutral-800 p-4`}>
                <p css={tw`font-medium text-neutral-100`}>Import completed Spark report</p>
                <p css={tw`mt-1 text-sm text-neutral-400`}>After Spark finishes, paste its official spark.lucko.me report link. Fluid imports only that report and extracts evidence-backed findings.</p>
                <div css={tw`mt-3 flex flex-col gap-3 sm:flex-row`}>
                    <input css={tw`flex-1 rounded border border-neutral-600 bg-neutral-900 px-3 py-2 text-neutral-100`} value={reportUrl} onChange={(event) => setReportUrl(event.target.value)} placeholder={'https://spark.lucko.me/abc123'} />
                    <Button color={'primary'} disabled={!reportUrl} onClick={importReport}>Import report</Button>
                </div>
            </div>
            {!!findings.length && <section css={tw`mb-8 space-y-3`}>
                <h2 css={tw`text-lg font-semibold text-neutral-100`}>Optimizer findings</h2>
                {findings.filter((finding) => !finding.ignored).map((finding) => <div key={finding.id} css={tw`rounded-lg border border-neutral-700 bg-neutral-800 p-4`}>
                    <div css={tw`flex flex-col justify-between gap-3 sm:flex-row`}>
                        <div>
                            <p css={tw`font-semibold text-neutral-100`}>{finding.title} <span className={severityClass(finding.severity)}>{finding.severity.toUpperCase()}</span></p>
                            <p css={tw`mt-2 text-sm text-neutral-300`}>{finding.explanation}</p>
                            <p css={tw`mt-2 text-xs text-neutral-400`}>
                                {finding.evidence?.key ? `Observed: ${finding.evidence.key} = ${finding.evidence.observed}` : 'Evidence imported from the official Spark report.'}
                                {` | Impact: ${finding.impact || 'unknown'}${finding.restart_required ? ' | Restart required' : ''}${finding.gameplay_change ? ' | May change gameplay' : ''}`}
                            </p>
                            {finding.recommendation?.file && <p css={tw`mt-2 text-sm text-blue-200`}>Recommended: {finding.recommendation.file} — {finding.recommendation.key} = {finding.recommendation.value}</p>}
                            {finding.source && <a css={tw`mt-2 inline-block text-xs text-blue-300 hover:text-blue-200`} href={finding.source} target={'_blank'} rel={'noreferrer'}>Authoritative reference</a>}
                        </div>
                        <div css={tw`flex h-min flex-wrap gap-2`}>
                            <Button size={'xsmall'} color={'grey'} onClick={() => action(`findings/${finding.id}/ignore`)}>Ignore</Button>
                            {finding.recommendation?.file && !finding.gameplay_change && <Button size={'xsmall'} color={'primary'} onClick={() => applyRecommendation(finding)}>Apply recommended setting</Button>}
                        </div>
                    </div>
                </div>)}
            </section>}
            <section>
                <h2 css={tw`mb-3 text-lg font-semibold text-neutral-100`}>Recent runs</h2>
                <div css={tw`space-y-2`}>{runs.map((run) => <div key={run.id} css={tw`flex items-center justify-between rounded bg-neutral-800 px-4 py-3 text-sm`}>
                    <span css={tw`text-neutral-200`}>{run.type.replace('_', ' ')}</span>
                    <span css={tw`text-neutral-400`}>{run.status}{run.summary?.message ? ` - ${run.summary.message}` : ''}{run.summary?.report_id ? <a css={tw`ml-2 text-blue-300 hover:text-blue-200`} href={`https://spark.lucko.me/${run.summary.report_id}`} target={'_blank'} rel={'noreferrer'}>Open Spark report</a> : null}</span>
                </div>)}</div>
            </section>
        </>}
    </ServerContentBlock>;
};

const Stat = ({ label, value }: { label: string; value: string }) => <div css={tw`rounded-lg border border-neutral-700 bg-neutral-800 p-4`}><p css={tw`text-xs font-medium uppercase tracking-wide text-neutral-400`}>{label}</p><p css={tw`mt-2 truncate text-sm font-semibold text-neutral-100`}>{value}</p></div>;
