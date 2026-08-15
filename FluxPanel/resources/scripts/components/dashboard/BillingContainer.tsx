import React from 'react';
import useSWR from 'swr';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faFileInvoiceDollar, faServer } from '@fortawesome/free-solid-svg-icons';
import getBilling, { BillingData } from '@/api/getBilling';
import PageContentBlock from '@/components/elements/PageContentBlock';
import Spinner from '@/components/elements/Spinner';
import MessageBox from '@/components/MessageBox';
import tw from 'twin.macro';

const money = (cents: number, currency = 'USD') =>
    new Intl.NumberFormat(undefined, { style: 'currency', currency }).format((cents || 0) / 100);

const date = (value: string | null) => (value ? new Date(value).toLocaleDateString() : '—');

export default () => {
    const { data, error } = useSWR<BillingData>('account-billing', getBilling);
    const summary = data?.summary || { monthly_total_cents: 0, next_billing_date: null };
    const nextBillingDate = summary.next_billing_date;

    return (
        <PageContentBlock title={'Billing'}>
            <div css={tw`mx-auto max-w-[1180px]`}>
                <header css={tw`flex h-[66px] items-center justify-between`}>
                    <h1 css={tw`text-[27px] font-semibold text-neutral-100`}>Billing</h1>
                    <a href={'https://fluxservers.cloud/account'} target={'_blank'} rel={'noreferrer'} css={tw`text-xs font-semibold text-blue-400 hover:text-blue-300`}>Manage billing ↗</a>
                </header>

                {error && <MessageBox title={'Billing unavailable'} type={'error'}>We could not load billing data right now. Please try again shortly.</MessageBox>}
                {!data && !error ? <Spinner centered size={'large'} /> : data && (
                    <>
                        <section css={tw`grid min-h-[90px] grid-cols-1 border-b border-t border-neutral-700 sm:grid-cols-2`}>
                            <div css={tw`border-b border-neutral-700 px-[22px] py-[18px] sm:border-b-0 sm:border-r`}>
                                <p css={tw`text-xl font-semibold text-neutral-100`}>{money(summary.monthly_total_cents)}</p>
                                <p css={tw`mt-1 text-[9px] font-medium uppercase tracking-wider text-neutral-400`}>Current monthly total</p>
                                <p css={tw`mt-1 text-[9px] text-neutral-600`}>{data.services.length} active services</p>
                            </div>
                            <div css={tw`px-[22px] py-[18px]`}>
                                <p css={tw`text-xl font-semibold text-neutral-100`}>{nextBillingDate ? new Date(nextBillingDate).toLocaleDateString(undefined, { day: '2-digit', month: 'short' }).toUpperCase() : '—'}</p>
                                <p css={tw`mt-1 text-[9px] font-medium uppercase tracking-wider text-neutral-400`}>Next billing date</p>
                                <p css={tw`mt-1 text-[9px] text-neutral-600`}>{money(summary.monthly_total_cents)} estimated</p>
                            </div>
                        </section>

                        <section>
                            <div css={tw`flex h-[58px] items-center justify-between`}><h2 css={tw`text-sm font-semibold text-neutral-100`}>Services</h2><a href={'/'} css={tw`text-[10px] font-medium text-neutral-400 hover:text-neutral-200`}>Manage services →</a></div>
                            <div css={tw`overflow-x-auto`}>
                                <table css={tw`w-full min-w-[760px] text-left`}><thead><tr css={tw`h-[34px] border-b border-neutral-700 text-[9px] font-medium uppercase tracking-wider text-neutral-400`}><th>Service</th><th>Plan</th><th>Billing</th><th>Price</th><th>Status</th></tr></thead><tbody>{data.services.map((service) => <tr key={service.identifier || service.created_at} css={tw`h-[52px] border-b border-neutral-700 text-[11px]`}><td css={tw`text-neutral-100`}><FontAwesomeIcon icon={faServer} css={tw`mr-3 text-neutral-500`} />{service.identifier || 'Server'}</td><td css={tw`text-neutral-300`}>{service.plan_name || '—'}</td><td css={tw`text-neutral-400`}>Monthly</td><td css={tw`text-neutral-100`}>—</td><td><span css={tw`rounded-full bg-green-500 bg-opacity-10 px-2 py-1 text-[9px] font-semibold uppercase text-green-400`}>{service.status}</span></td></tr>)}</tbody></table>
                            </div>
                            {!data.services.length && <p css={tw`border-b border-neutral-700 py-5 text-sm text-neutral-500`}>No active services found.</p>}
                        </section>

                        <section>
                            <div css={tw`flex h-[58px] items-center justify-between`}><h2 css={tw`text-sm font-semibold text-neutral-100`}>Invoices</h2><span css={tw`text-[10px] font-medium text-neutral-400`}>Payment history</span></div>
                            <div css={tw`overflow-x-auto`}>
                                <table css={tw`w-full min-w-[760px] text-left`}><thead><tr css={tw`h-[34px] border-b border-neutral-700 text-[9px] font-medium uppercase tracking-wider text-neutral-400`}><th>Invoice</th><th>Description</th><th>Date</th><th>Total</th><th>Status</th></tr></thead><tbody>{data.invoices.map((invoice) => <tr key={invoice.public_id} css={tw`h-[52px] border-b border-neutral-700 text-[11px]`}><td css={tw`font-mono text-neutral-300`}>{invoice.public_id.slice(0, 8)}</td><td css={tw`text-neutral-100`}><FontAwesomeIcon icon={faFileInvoiceDollar} css={tw`mr-3 text-neutral-500`} />{invoice.description}</td><td css={tw`text-neutral-400`}>{date(invoice.created_at)}</td><td css={tw`text-neutral-100`}>{money(invoice.total_cents, invoice.currency)}</td><td css={tw`text-neutral-300`}>{invoice.status}</td></tr>)}</tbody></table>
                            </div>
                            {!data.invoices.length && <p css={tw`border-b border-neutral-700 py-5 text-sm text-neutral-500`}>No invoices found.</p>}
                        </section>
                    </>
                )}
            </div>
        </PageContentBlock>
    );
};
