import React from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faBook, faCreditCard, faLifeRing } from '@fortawesome/free-solid-svg-icons';
import PageContentBlock from '@/components/elements/PageContentBlock';
import tw from 'twin.macro';

const topics = [
    { icon: faLifeRing, title: 'Technical support', text: 'Get help with server access, performance, and configuration.' },
    { icon: faCreditCard, title: 'Billing support', text: 'Questions about invoices, payments, or active services.' },
    { icon: faBook, title: 'Documentation', text: 'Read common setup and troubleshooting guidance.' },
];

export default () => (
    <PageContentBlock title={'Support'}>
        <div css={tw`mx-auto max-w-[1180px]`}>
            <header css={tw`flex h-[66px] items-center justify-between`}><h1 css={tw`text-[27px] font-semibold text-neutral-100`}>Support</h1><a href={'https://fluxservers.cloud/contact'} target={'_blank'} rel={'noreferrer'} css={tw`flex h-[34px] items-center rounded bg-blue-500 px-5 text-[10px] font-semibold text-neutral-100 no-underline hover:bg-blue-400`}>New ticket</a></header>
            <section>
                <div css={tw`flex h-[58px] items-center justify-between`}><h2 css={tw`text-sm font-semibold text-neutral-100`}>Your tickets</h2><a href={'https://fluxservers.cloud/contact'} target={'_blank'} rel={'noreferrer'} css={tw`text-[10px] font-medium text-neutral-400 hover:text-neutral-200`}>View ticket history →</a></div>
                <div css={tw`overflow-x-auto`}><div css={tw`grid min-w-[900px] border-b border-neutral-700 text-[9px] font-medium uppercase tracking-wider text-neutral-400`} style={{ gridTemplateColumns: '130px 410px 220px 180px 240px' }}><span>Ticket</span><span>Subject</span><span>Server</span><span>Status</span><span>Updated</span></div><div css={tw`grid min-w-[900px] min-h-[52px] items-center border-b border-neutral-700 text-[11px]`} style={{ gridTemplateColumns: '130px 410px 220px 180px 240px' }}><span css={tw`text-neutral-500`}>—</span><span css={tw`text-neutral-500`}>No tickets yet</span><span css={tw`text-neutral-500`}>—</span><span css={tw`text-neutral-500`}>—</span><span css={tw`text-neutral-500`}>—</span></div></div>
            </section>
            <section>
                <div css={tw`flex h-[58px] items-center`}><h2 css={tw`text-sm font-semibold text-neutral-100`}>Get help</h2></div>
                <div css={tw`grid gap-4 md:grid-cols-3`}>{topics.map(({ icon, title, text }) => <a href={'https://fluxservers.cloud/contact'} target={'_blank'} rel={'noreferrer'} key={title} css={tw`min-h-[130px] border border-neutral-700 p-5 no-underline transition-colors hover:border-blue-500`}><FontAwesomeIcon icon={icon} css={tw`mb-4 text-lg text-blue-400`} /><h3 css={tw`mb-2 text-sm font-semibold text-neutral-100`}>{title}</h3><p css={tw`text-[11px] leading-5 text-neutral-400`}>{text}</p></a>)}</div>
            </section>
        </div>
    </PageContentBlock>
);
