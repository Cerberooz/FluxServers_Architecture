import React, { useState } from 'react';
import useSWR from 'swr';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faLifeRing } from '@fortawesome/free-solid-svg-icons';
import { createSupportTicket, getSupport, SupportTicketInput } from '@/api/getSupport';
import { httpErrorToHuman } from '@/api/http';
import PageContentBlock from '@/components/elements/PageContentBlock';
import Spinner from '@/components/elements/Spinner';
import tw from 'twin.macro';

const emptyForm: SupportTicketInput = { email: '', subject: '', details: '' };

export default () => {
    const { data, error, mutate } = useSWR('support-tickets', getSupport);
    const [form, setForm] = useState(emptyForm);
    const [submitting, setSubmitting] = useState(false);
    const [notice, setNotice] = useState<string>();
    const [formError, setFormError] = useState<string>();

    const update = (field: keyof SupportTicketInput, value: string) => setForm((current) => ({ ...current, [field]: value }));

    const submit = async (event: React.FormEvent) => {
        event.preventDefault();
        setSubmitting(true);
        setNotice(undefined);
        setFormError(undefined);
        try {
            await createSupportTicket(form);
            setForm(emptyForm);
            setNotice('Your support ticket has been submitted. We will review it shortly.');
            await mutate();
        } catch (submitError) {
            setFormError(httpErrorToHuman(submitError));
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <PageContentBlock title={'Support'}>
            <div css={tw`mx-auto max-w-[1180px]`}>
                <header css={tw`flex h-[66px] items-center`}><div><h1 css={tw`text-[27px] font-semibold text-neutral-100`}>Support</h1><p css={tw`mt-1 text-sm text-neutral-500`}>Get help from the Fluid support team.</p></div></header>

                <section css={tw`border-t border-neutral-700`}>
                    <div css={tw`flex min-h-[58px] items-center gap-3`}><FontAwesomeIcon icon={faLifeRing} css={tw`text-blue-400`} /><h2 css={tw`text-sm font-semibold text-neutral-100`}>Submit a support ticket</h2></div>
                    {notice && <div css={tw`mb-5 rounded border border-green-700 bg-green-900 bg-opacity-20 px-4 py-3 text-sm text-green-300`}>{notice}</div>}
                    {formError && <div css={tw`mb-5 rounded border border-red-700 bg-red-900 bg-opacity-20 px-4 py-3 text-sm text-red-300`}>{formError}</div>}
                    <form onSubmit={submit} css={tw`max-w-[760px]`}>
                        <div css={tw`grid gap-5 sm:grid-cols-2`}>
                            <label css={tw`block`}><span css={tw`mb-2 block text-[10px] font-semibold uppercase tracking-wider text-neutral-400`}>Email</span><input type={'email'} required value={form.email} onChange={(event) => update('email', event.target.value)} placeholder={'you@example.com'} css={tw`w-full rounded border border-neutral-700 bg-neutral-900 px-3 py-3 text-sm text-neutral-100 outline-none transition-colors placeholder:text-neutral-600 focus:border-blue-500`} /></label>
                            <label css={tw`block`}><span css={tw`mb-2 block text-[10px] font-semibold uppercase tracking-wider text-neutral-400`}>Subject</span><input required maxLength={191} value={form.subject} onChange={(event) => update('subject', event.target.value)} placeholder={'How can we help?'} css={tw`w-full rounded border border-neutral-700 bg-neutral-900 px-3 py-3 text-sm text-neutral-100 outline-none transition-colors placeholder:text-neutral-600 focus:border-blue-500`} /></label>
                        </div>
                        <label css={tw`mt-5 block`}><span css={tw`mb-2 block text-[10px] font-semibold uppercase tracking-wider text-neutral-400`}>Details</span><textarea required maxLength={10000} rows={7} value={form.details} onChange={(event) => update('details', event.target.value)} placeholder={'Describe the issue, including any relevant server or error details.'} css={tw`w-full resize-y rounded border border-neutral-700 bg-neutral-900 px-3 py-3 text-sm leading-6 text-neutral-100 outline-none transition-colors placeholder:text-neutral-600 focus:border-blue-500`} /></label>
                        <button type={'submit'} disabled={submitting} css={tw`mt-5 inline-flex h-10 items-center rounded border border-blue-500 bg-blue-600 px-5 text-xs font-semibold text-blue-50 transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50`}>{submitting ? 'Submitting...' : 'Submit ticket'}</button>
                    </form>
                </section>

                <section css={tw`mt-8`}>
                    <div css={tw`flex h-[58px] items-center justify-between`}><h2 css={tw`text-sm font-semibold text-neutral-100`}>Your tickets</h2><span css={tw`text-[10px] text-neutral-500`}>{data?.pagination.total || 0} total</span></div>
                    {error && <p css={tw`border-y border-neutral-700 py-5 text-sm text-red-300`}>Could not load your tickets.</p>}
                    {!data && !error ? <Spinner centered size={'large'} /> : data && <div css={tw`overflow-x-auto`}>
                        <table css={tw`w-full min-w-[760px] text-left`}><thead><tr css={tw`h-[34px] border-b border-neutral-700 text-[9px] font-medium uppercase tracking-wider text-neutral-400`}><th>Ticket</th><th>Subject</th><th>Status</th><th>Submitted</th></tr></thead><tbody>
                            {data.tickets.map((ticket) => <tr key={ticket.id} css={tw`border-b border-neutral-700 text-[11px]`}><td css={tw`py-4 font-mono text-neutral-400`}>#{ticket.id}</td><td css={tw`py-4 text-neutral-100`}>{ticket.subject}</td><td css={tw`py-4 uppercase text-neutral-300`}>{ticket.status.replace('_', ' ')}</td><td css={tw`py-4 text-neutral-400`}>{new Date(ticket.created_at).toLocaleDateString()}</td></tr>)}
                        </tbody></table>
                        {!data.tickets.length && <p css={tw`border-b border-neutral-700 py-5 text-sm text-neutral-500`}>No support tickets yet.</p>}
                    </div>}
                </section>
            </div>
        </PageContentBlock>
    );
};
