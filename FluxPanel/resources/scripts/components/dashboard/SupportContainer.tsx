import React from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faBook, faCreditCard, faLifeRing } from '@fortawesome/free-solid-svg-icons';
import PageContentBlock from '@/components/elements/PageContentBlock';
import tw from 'twin.macro';

const topics = [
    { icon: faLifeRing, title: 'Technical support', text: 'Get help with server access, performance, and configuration.' },
    { icon: faCreditCard, title: 'Billing support', text: 'Questions about invoices, payments, or your active services.' },
    { icon: faBook, title: 'Documentation', text: 'Read common setup and troubleshooting guidance.' },
];

export default () => (
    <PageContentBlock title={'Support'}>
        <div css={tw`mb-8 flex items-center justify-between`}>
            <div><h1 css={tw`text-3xl font-semibold text-neutral-100`}>Support</h1><p css={tw`mt-2 text-sm text-neutral-400`}>Need a hand? We are here to help.</p></div>
            <a href={'https://fluxservers.cloud/contact'} target={'_blank'} rel={'noreferrer'} css={tw`rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500`}>New ticket ↗</a>
        </div>
        <div css={tw`grid gap-4 md:grid-cols-3`}>
            {topics.map(({ icon, title, text }) => <a href={'https://fluxservers.cloud/contact'} target={'_blank'} rel={'noreferrer'} key={title} css={tw`rounded-xl border border-neutral-700 bg-neutral-800 p-5 no-underline transition-colors hover:border-blue-500`}><FontAwesomeIcon icon={icon} css={tw`mb-5 text-xl text-blue-400`} /><h2 css={tw`mb-2 text-lg font-semibold text-neutral-100`}>{title}</h2><p css={tw`text-sm leading-6 text-neutral-400`}>{text}</p></a>)}
        </div>
    </PageContentBlock>
);
