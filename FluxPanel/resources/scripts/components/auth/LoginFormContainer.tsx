import React, { forwardRef } from 'react';
import { Form } from 'formik';
import styled from 'styled-components/macro';
import FlashMessageRender from '@/components/FlashMessageRender';
import tw from 'twin.macro';

type Props = React.DetailedHTMLProps<React.FormHTMLAttributes<HTMLFormElement>, HTMLFormElement> & {
    title?: string;
    subtitle?: string;
};

const Container = styled.div`
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    width: 100%;
    min-height: 100vh;
    background: #0b0d12;

    @media (min-width: 768px) {
        grid-template-columns: minmax(420px, 1.05fr) minmax(360px, 0.95fr);
    }
`;

const FormPane = styled.div`
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 48px 28px;
    background: #111620;

    @media (min-width: 768px) {
        padding: 64px;
        border-right: 1px solid #252c38;
    }
`;

const FormContent = styled.div`
    width: 100%;
    max-width: 520px;
`;

const BrandPane = styled.aside`
    display: none;
    align-items: center;
    justify-content: center;
    padding: 64px;
    background: #080a0f;

    @media (min-width: 768px) {
        display: flex;
    }
`;

const BrandLogo = styled.img`
    width: min(72%, 390px);
    height: auto;
    border-radius: 28px;
    object-fit: cover;
    box-shadow: 0 28px 80px rgba(0, 0, 0, 0.35);
`;

const MobileLogo = styled.img`
    width: 56px;
    height: 56px;
    margin-bottom: 24px;
    border: 1px solid #4b5563;
    border-radius: 14px;
    object-fit: cover;

    @media (min-width: 768px) {
        display: none;
    }
`;

const FormCard = styled.div`
    ${tw`w-full`};

    label {
        color: #cbd5e1 !important;
    }

    input:not([type='checkbox']):not([type='radio']) {
        background: #141923 !important;
        border-color: #374151 !important;
        color: #f3f4f6 !important;
        box-shadow: none !important;
    }

    input:not([type='checkbox']):not([type='radio']):hover {
        border-color: #4b5563 !important;
    }

    input:not([type='checkbox']):not([type='radio']):focus {
        border-color: #0891b2 !important;
        box-shadow: 0 0 0 3px rgba(8, 145, 178, 0.16) !important;
    }

    input::placeholder {
        color: #7d899a !important;
        opacity: 1 !important;
    }
`;

export default forwardRef<HTMLFormElement, Props>(({ title, subtitle = 'Sign in to manage your servers.', ...props }, ref) => (
    <Container>
        <FormPane>
            <FormContent>
                <MobileLogo src={'/favicons/flux_logo.jpg'} alt={'Fluid'} />
                <div css={tw`mb-8`}>
                    {title && <h2 css={tw`text-3xl text-neutral-100 font-semibold`}>{title}</h2>}
                    <p css={tw`text-base text-neutral-400 mt-2`}>{subtitle}</p>
                </div>
                <FlashMessageRender css={tw`mb-4`} />
                <Form {...props} ref={ref}>
                    <FormCard>{props.children}</FormCard>
                </Form>
                <p css={tw`text-neutral-500 text-xs mt-6`}>
                    Fluid Panel &copy; {new Date().getFullYear()}
                </p>
            </FormContent>
        </FormPane>
        <BrandPane>
            <BrandLogo src={'/favicons/flux_logo.jpg'} alt={'Fluid'} />
        </BrandPane>
    </Container>
));
