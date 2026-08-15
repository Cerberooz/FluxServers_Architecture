import React from 'react';
import useSWR from 'swr';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faFileInvoiceDollar, faServer } from '@fortawesome/free-solid-svg-icons';
import getBilling, { BillingData } from '@/api/getBilling';
import PageContentBlock from '@/components/elements/PageContentBlock';
import Spinner from '@/components/elements/Spinner';
import MessageBox from '@/components/MessageBox';
import tw from 'twin.macro';

const money = (cents: number, currency: string) =>
    new Intl.NumberFormat(undefined, { style: 'currency', currency: currency || 'USD' }).format((cents || 0) / 100);
const date = (value: string | null) => (value ? new Date(value).toLocaleDateString() : '—');

const Table = ({ children }: { children: React.ReactNode }) => (
    <div css={tw`overflow-x-auto rounded-xl border border-neutral-700 bg-neutral-800`}>{children}</div>
);

export default () => {
    const { data, error } = useSWR<BillingData>('account-billing', getBilling);

    return (
        <PageContentBlock title={'Billing'}>
            <div css={tw`mb-8 flex items-center justify-between`}>
                <div>
                    <h1 css={tw`text-3xl font-semibold text-neutral-100`}>Billing</h1>
                    <p css={tw`mt-2 text-sm text-neutral-400`}>View your active services and payment history.</p>
                </div>
                <a href={'https://fluxservers.cloud/account'} target={'_blank'} rel={'noreferrer'} css={tw`text-sm text-cyan-400 hover:text-cyan-300`}>
                    Manage billing ↗
                </a>
            </div>
            {error && <MessageBox title={'Billing unavailable'} type={'error'}>We could not load billing data right now. Your servers remain accessible.</MessageBox>}
            {!data && !error ? <Spinner centered size={'large'} /> : data && (
                <>
                    <div css={tw`mb-8 grid grid-cols-1 gap-4 md:grid-cols-2`}>
                        <div css={tw`rounded-xl border border-neutral-700 bg-neutral-800 p-5`}><p css={tw`text-xs uppercase tracking-wider text-neutral-400`}>Active services</p><p css={tw`mt-3 text-2xl font-semibold text-neutral-100`}>{data.services.length}</p></div>
                        <div css={tw`rounded-xl border border-neutral-700 bg-neutral-800 p-5`}><p css={tw`text-xs uppercase tracking-wider text-neutral-400`}>Current monthly total</p><p css={tw`mt-3 text-2xl font-semibold text-neutral-100`}>{money(data.summary.monthly_total_cents, 'USD')}</p></div>
                    </div>
                    <section css={tw`mb-8`}>
                        <h2 css={tw`mb-3 text-lg font-semibold text-neutral-100`}>Services</h2>
                        <Table><table css={tw`w-full text-left text-sm`}><thead css={tw`border-b border-neutral-700 text-xs uppercase tracking-wider text-neutral-400`}><tr><th css={tw`px-5 py-4`}>Service</th><th css={tw`px-5 py-4`}>Plan</th><th css={tw`px-5 py-4`}>Region</th><th css={tw`px-5 py-4`}>Status</th><th css={tw`px-5 py-4`}>Expires</th></tr></thead><tbody>{data.services.map((service) => <tr key={service.identifier || service.created_at} css={tw`border-b border-neutral-700 last:border-0`}><td css={tw`px-5 py-4 text-neutral-100`}><FontAwesomeIcon icon={faServer} css={tw`mr-3 text-neutral-500`} />{service.identifier || 'Server'}</td><td css={tw`px-5 py-4 text-neutral-300`}>{service.plan_name || '—'}</td><td css={tw`px-5 py-4 text-neutral-300`}>{service.node_name || '—'}</td><td css={tw`px-5 py-4`}><span css={tw`rounded-full bg-green-500 bg-opacity-10 px-3 py-1 text-xs text-green-400`}>{service.status}</span></td><td css={tw`px-5 py-4 text-neutral-300`}>{date(service.expires_at)}</td></tr>)}</tbody></table>{!data.services.length && <p css={tw`p-6 text-sm text-neutral-400`}>No active services found.</p>}</Table>
                    </section>
                    <section>
                        <h2 css={tw`mb-3 text-lg font-semibold text-neutral-100`}>Invoices</h2>
                        <Table><table css={tw`w-full text-left text-sm`}><thead css={tw`border-b border-neutral-700 text-xs uppercase tracking-wider text-neutral-400`}><tr><th css={tw`px-5 py-4`}>Invoice</th><th css={tw`px-5 py-4`}>Description</th><th css={tw`px-5 py-4`}>Date</th><th css={tw`px-5 py-4`}>Total</th><th css={tw`px-5 py-4`}>Status</th></tr></thead><tbody>{data.invoices.map((invoice) => <tr key={invoice.public_id} css={tw`border-b border-neutral-700 last:border-0`}><td css={tw`px-5 py-4 font-mono text-xs text-neutral-300`}>{invoice.public_id.slice(0, 8)}</td><td css={tw`px-5 py-4 text-neutral-100`}><FontAwesomeIcon icon={faFileInvoiceDollar} css={tw`mr-3 text-neutral-500`} />{invoice.description}</td><td css={tw`px-5 py-4 text-neutral-300`}>{date(invoice.created_at)}</td><td css={tw`px-5 py-4 text-neutral-100`}>{money(invoice.total_cents, invoice.currency)}</td><td css={tw`px-5 py-4 text-neutral-300`}>{invoice.status}</td></tr>)}</tbody></table>{!data.invoices.length && <p css={tw`p-6 text-sm text-neutral-400`}>No invoices found.</p>}</Table>
                    </section>
                </>
            )}
        </PageContentBlock>
    );
};
