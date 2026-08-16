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

    .fluid-dashboard { color: #ecf1f9; }
    .fluid-dashboard__header {
        display: flex; min-height: 97px; align-items: flex-start; justify-content: space-between;
        padding: 4px 0 24px; border-bottom: 1px solid #17202e;
    }
    .fluid-dashboard__header h1 { margin: 0; color: #ecf1f9; font-size: 24px; font-weight: 600; line-height: 1.2; }
    .fluid-dashboard__header p { margin: 10px 0 0; color: #6e83a2; font-size: 10px; }
    .fluid-dashboard__header p span { padding: 0 5px; }
    .fluid-dashboard__status { display: inline-flex; gap: 7px; align-items: center; margin-top: 7px; color: #6e83a2; font-size: 9px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; }
    .fluid-dashboard__status i { width: 7px; height: 7px; border-radius: 999px; background: #5a6f91; }
    .fluid-dashboard__status.is-online { color: #25d281; }
    .fluid-dashboard__status.is-online i { background: #25d281; }
    .fluid-dashboard-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; margin-top: 20px; }
    .fluid-dashboard-card { min-height: 236px; border: 1px solid #17202e; background: #05070a; }
    .fluid-dashboard-card > header, .fluid-quick-access > header { padding: 15px 17px; border-bottom: 1px solid #17202e; }
    .fluid-dashboard-card > .fluid-dashboard-card__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
    .fluid-dashboard-card__header > a { flex: 0 0 auto; margin-top: -3px; padding: 7px 11px; border: 1px solid #17202e; border-radius: 4px; color: #2582ff; font-size: 9px; font-weight: 500; line-height: 1.2; text-decoration: none; }
    .fluid-dashboard-card__header > a:hover { border-color: #2582ff; background: #080b11; }
    .fluid-dashboard-card__header > a span { padding-left: 4px; }
    .fluid-dashboard-card h2, .fluid-quick-access h2 { margin: 0; color: #ecf1f9; font-size: 13px; font-weight: 600; }
    .fluid-dashboard-card header p, .fluid-quick-access header p { margin: 6px 0 0; color: #6e83a2; font-size: 9px; }
    .fluid-dashboard-detail { display: grid; grid-template-columns: 136px minmax(0, 1fr); min-height: 35px; align-items: center; padding: 0 17px; border-bottom: 1px solid #17202e; }
    .fluid-dashboard-detail:last-child { border-bottom: 0; }
    .fluid-dashboard-detail > span, .fluid-dashboard-usage span { color: #4f6280; font-size: 8px; font-weight: 500; letter-spacing: .08em; text-transform: uppercase; }
    .fluid-dashboard-detail strong { overflow: hidden; color: #ecf1f9; font-size: 11px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
    .fluid-dashboard-activity { min-height: 204px; }
    .fluid-dashboard-activity__item { display: grid; grid-template-columns: 7px minmax(0, 1fr) auto; gap: 10px; align-items: start; min-height: 47px; padding: 10px 16px; border-bottom: 1px solid #17202e; }
    .fluid-dashboard-activity__item:last-child { border-bottom: 0; }
    .fluid-dashboard-activity__item > i { width: 6px; height: 6px; margin-top: 5px; border-radius: 999px; background: #25c8e8; }
    .fluid-dashboard-activity__item strong { display: block; overflow: hidden; color: #ecf1f9; font-size: 11px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
    .fluid-dashboard-activity__item p { overflow: hidden; margin: 4px 0 0; color: #6e83a2; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
    .fluid-dashboard-activity__item time { margin-top: 5px; color: #4f6280; font-size: 9px; white-space: nowrap; }
    .fluid-dashboard-empty { padding: 45px 20px; color: #6e83a2; font-size: 11px; text-align: center; }
    .fluid-dashboard-usages { padding: 15px 17px; }
    .fluid-dashboard-usage { margin-bottom: 13px; }
    .fluid-dashboard-usage:last-child { margin-bottom: 0; }
    .fluid-dashboard-usage > div:first-child { display: flex; justify-content: space-between; gap: 12px; }
    .fluid-dashboard-usage strong { color: #ecf1f9; font-size: 11px; font-weight: 600; white-space: nowrap; }
    .fluid-dashboard-usage__track { height: 5px; margin-top: 9px; overflow: hidden; border-radius: 1px; background: #080b11; }
    .fluid-dashboard-usage__track i { display: block; height: 100%; border-radius: inherit; background: #2582ff; }
    .fluid-quick-access { margin-top: 22px; border-top: 1px solid #17202e; border-bottom: 1px solid #17202e; }
    .fluid-quick-access > header { padding: 18px 0; border-bottom: 0; }
    .fluid-quick-access > div { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); padding: 12px 0 18px; }
    .fluid-quick-access a { min-height: 76px; padding: 0 18px; border-right: 1px solid #17202e; color: inherit; text-decoration: none; }
    .fluid-quick-access a:first-child { padding-left: 18px; }
    .fluid-quick-access a:last-child { border-right: 0; }
    .fluid-quick-access a:hover { background: #080b11; }
    .fluid-quick-access strong { display: block; color: #ecf1f9; font-size: 12px; font-weight: 600; }
    .fluid-quick-access p { min-height: 28px; margin: 8px 0 5px; color: #6e83a2; font-size: 9px; }
    .fluid-quick-access span { color: #2582ff; font-size: 9px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; }

    @media (max-width: 768px) {
        .fluid-dashboard-grid, .fluid-quick-access > div { grid-template-columns: 1fr; }
        .fluid-quick-access a { padding: 14px 0; border-right: 0; border-bottom: 1px solid #17202e; }
        .fluid-quick-access a:last-child { border-bottom: 0; }
    }

    .fluid-console-identity { display: grid; grid-template-columns: 2fr .9fr 1.3fr 1.1fr; margin-top: 15px; border-top: 1px solid #17202e; border-bottom: 1px solid #17202e; }
    .fluid-console-identity > div { min-height: 69px; padding: 16px 18px; border-right: 1px solid #17202e; }
    .fluid-console-identity > div:last-child { border-right: 0; }
    .fluid-console-identity span { display: block; color: #4f6280; font-size: 8px; font-weight: 500; letter-spacing: .08em; text-transform: uppercase; }
    .fluid-console-identity strong { display: block; overflow: hidden; margin-top: 7px; color: #ecf1f9; font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
    .fluid-console-copy-address { display: flex; width: 100%; align-items: center; justify-content: flex-start; gap: 8px; padding: 0; border: 0; background: transparent; color: inherit; cursor: pointer; }
    .fluid-console-copy-address strong { flex: 0 1 auto; max-width: none; }
    .fluid-console-copy-address svg { flex: 0 0 auto; color: #6e83a2; font-size: 10px; }
    .fluid-console-copy-address:hover svg { color: #2582ff; }
    .fluid-console-layout { display: grid; grid-template-columns: minmax(0, 1fr) 318px; gap: 20px; margin-top: 20px; }
    .fluid-console-surface { min-height: 414px; overflow: hidden; border: 1px solid #17202e; border-radius: 4px; background: #05070a; }
    .fluid-console-surface > header { display: flex; min-height: 57px; align-items: center; justify-content: space-between; padding: 0 17px; border-bottom: 1px solid #17202e; }
    .fluid-console-surface h2 { margin: 0; color: #ecf1f9; font-size: 13px; font-weight: 600; }
    .fluid-console-surface header p { margin: 5px 0 0; color: #6e83a2; font-size: 9px; }
    .fluid-console-terminal { height: 355px; min-height: 0; }
    .fluid-console-controls { display: flex; gap: 8px; }
    .fluid-console-controls button { min-height: 30px; padding: 0 15px; font-size: 10px; }
    .fluid-console-resources > div { display: grid; grid-template-columns: 1fr; gap: 0; }
    .fluid-console-resource-list { display: flex; flex-direction: column; }
    .fluid-console-resource-row { min-height: 65px; padding: 12px 17px; border-bottom: 1px solid #17202e; }
    .fluid-console-resource-row:last-child { border-bottom: 0; }
    .fluid-console-resource-row > span { display: block; color: #4f6280; font-size: 8px; font-weight: 500; letter-spacing: .08em; text-transform: uppercase; }
    .fluid-console-resource-row > div { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-top: 6px; }
    .fluid-console-resource-row strong { overflow: hidden; color: #ecf1f9; font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
    .fluid-console-resource-row small { flex: 0 0 auto; color: #6e83a2; font-size: 9px; }
    .fluid-console-graphs { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; margin-top: 20px; }
    .fluid-console-graphs .chart_container h3 { color: #ecf1f9; font-size: 12px; font-weight: 600; }
    .fluid-console-graphs .chart_container > div:first-child { min-height: 48px; padding: 0 16px; border-bottom: 1px solid #17202e; }

    @media (max-width: 1024px) {
        .fluid-console-layout { grid-template-columns: 1fr; }
        .fluid-console-resources > div { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .fluid-console-resource-row:nth-last-child(-n+2) { border-bottom: 0; }
        .fluid-console-graphs { grid-template-columns: 1fr; }
    }
    @media (max-width: 640px) {
        .fluid-console-identity { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .fluid-console-identity > div:nth-child(2) { border-right: 0; }
        .fluid-console-identity > div:nth-child(-n+2) { border-bottom: 1px solid #17202e; }
        .fluid-console-resources > div { grid-template-columns: 1fr; }
        .fluid-console-resource-row { border-bottom: 1px solid #17202e !important; }
        .fluid-console-resource-row:last-child { border-bottom: 0 !important; }
    }

    @media (max-width: 640px) {
        .fluid-server-page__header { min-height: 82px; padding-bottom: 17px; }
        .fluid-server-page .fluid-table__head { display: none; }
    }
`;
