import styled from 'styled-components/macro';
import tw from 'twin.macro';

export default styled.div<{ $hoverable?: boolean }>`
    ${tw`flex rounded-lg no-underline text-neutral-200 items-center bg-neutral-800 p-5 border border-neutral-600 transition-colors duration-150 overflow-hidden shadow-md`};

    ${(props) => props.$hoverable !== false && tw`hover:border-cyan-700 hover:bg-neutral-700`};

    & .icon {
        ${tw`rounded-lg w-14 flex items-center justify-center bg-neutral-700 border border-neutral-600 p-3`};
    }
`;
