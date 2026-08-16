import tw from 'twin.macro';
import { createGlobalStyle } from 'styled-components/macro';
// @ts-expect-error untyped font file
import font from '@fontsource-variable/inter/files/inter-latin-wght-normal.woff2';

export default createGlobalStyle`
    html {
        /* Keep the viewport width stable when an absolute menu opens. */
        overflow-y: scroll;
    }

    @font-face {
        font-family: 'Inter';
        font-style: normal;
        font-display: swap;
        font-weight: 100 700;
        src: url(${font}) format('woff2-variations');
        unicode-range: U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD;
    }

    body {
        ${tw`font-sans bg-neutral-800 text-neutral-200`};
        font-family: 'Inter', system-ui, sans-serif;
        letter-spacing: 0;
        background:
            linear-gradient(180deg, #0b0d12 0%, #0e1118 42%, #0b0d12 100%);
        min-height: 100vh;
    }

    h1, h2, h3, h4, h5, h6 {
        ${tw`font-medium tracking-normal font-header`};
    }

    p {
        ${tw`text-neutral-200 leading-snug font-sans`};
    }

    form {
        ${tw`m-0`};
    }

    textarea, select, input, button, button:focus, button:focus-visible {
        ${tw`outline-none`};
    }

    input[type=number]::-webkit-outer-spin-button,
    input[type=number]::-webkit-inner-spin-button {
        -webkit-appearance: none !important;
        margin: 0;
    }

    input[type=number] {
        -moz-appearance: textfield !important;
    }

    /* Scroll Bar Style */
    ::-webkit-scrollbar {
        background: none;
        width: 16px;
        height: 16px;
    }

    ::-webkit-scrollbar-thumb {
        border: solid 0 rgb(0 0 0 / 0%);
        border-right-width: 4px;
        border-left-width: 4px;
        -webkit-border-radius: 9px 4px;
        -webkit-box-shadow: inset 0 0 0 1px #202532, inset 0 0 0 4px #151a24;
    }

    ::-webkit-scrollbar-track-piece {
        margin: 4px 0;
    }

    ::-webkit-scrollbar-thumb:horizontal {
        border-right-width: 0;
        border-left-width: 0;
        border-top-width: 4px;
        border-bottom-width: 4px;
        -webkit-border-radius: 4px 9px;
    }

    ::-webkit-scrollbar-corner {
        background: transparent;
    }

    .fluid-server-page {
        color: #ecf1f9;
    }

    .fluid-server-page__header {
        min-height: 97px;
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        border-bottom: 1px solid #17202e;
        padding: 4px 0 24px;
    }

    .fluid-server-page__header h1 {
        margin: 0;
        color: #ecf1f9;
        font-size: 24px;
        font-weight: 600;
        line-height: 1.2;
    }

    .fluid-server-page__header p {
        margin: 10px 0 0;
        color: #6e83a2;
        font-size: 10px;
    }

    .fluid-server-page__header p span { padding: 0 5px; }

    .fluid-server-page__status {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        margin-top: 7px;
        color: #6e83a2;
        font-size: 9px;
        font-weight: 600;
        letter-spacing: .06em;
        text-transform: uppercase;
    }

    .fluid-server-page__status i { width: 7px; height: 7px; border-radius: 999px; background: #5a6f91; }
    .fluid-server-page__status--running { color: #25d281; }
    .fluid-server-page__status--running i { background: #25d281; }
    .fluid-server-page__content { padding-top: 20px; }

    .fluid-server-page .fluid-surface,
    .fluid-server-page .fluid-table {
        border: 1px solid #17202e;
        border-radius: 4px;
        background: #05070a;
    }

    .fluid-server-page .fluid-table { overflow: hidden; }
    .fluid-server-page .fluid-table__head {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 160px 190px 36px;
        gap: 16px;
        align-items: center;
        min-height: 48px;
        padding: 0 20px;
        border-bottom: 1px solid #17202e;
        color: #4f6280;
        font-size: 8px;
        font-weight: 500;
        letter-spacing: .08em;
        text-transform: uppercase;
    }

    .fluid-server-page .fluid-table > .fluid-row,
    .fluid-server-page .fluid-table > a.fluid-row {
        border: 0;
        border-bottom: 1px solid #17202e;
        border-radius: 0;
        background: transparent;
        box-shadow: none;
    }

    .fluid-server-page .fluid-table > .fluid-row:last-child,
    .fluid-server-page .fluid-table > a.fluid-row:last-child { border-bottom: 0; }
    .fluid-server-page .fluid-row { min-height: 58px; padding: 12px 20px; }

    .fluid-server-page .fluid-activity { background: #05070a; }
    .fluid-server-page .fluid-activity-row {
        padding: 16px 20px;
        border-color: #17202e;
        background: transparent;
    }
    .fluid-server-page .fluid-activity-row:hover { background: #080b11; }
    .fluid-server-page .fluid-activity-row .description { color: #ecf1f9; font-size: 11px; }

    @media (max-width: 640px) {
        .fluid-server-page__header { min-height: 82px; padding-bottom: 17px; }
        .fluid-server-page .fluid-table__head { display: none; }
    }
`;
