import styled, { css } from 'styled-components/macro';
import tw from 'twin.macro';

export default styled.div<{ $hoverable?: boolean }>`
    ${tw`flex no-underline text-neutral-200 items-center p-5 transition-colors duration-150 overflow-hidden`};
    border: 1px solid #17202e;
    border-radius: 4px;
    background: #05070a;
    box-shadow: none;

    ${(props) => props.$hoverable !== false && css`&:hover { border-color: #30415c; background: #080b11; }`};

    & .icon {
        ${tw`w-14 flex items-center justify-center p-3`};
        border: 1px solid #17202e;
        border-radius: 4px;
        background: #0a0e15;
    }
`;
