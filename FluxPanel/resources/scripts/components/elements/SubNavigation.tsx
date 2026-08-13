import styled from 'styled-components/macro';
import tw, { theme } from 'twin.macro';

const SubNavigation = styled.div`
    ${tw`w-full bg-neutral-800 border-b border-neutral-600 shadow overflow-x-auto`};

    & > div {
        ${tw`flex items-center text-sm mx-auto px-4 sm:px-6`};
        max-width: 1280px;

        & > a,
        & > div {
            ${tw`inline-block my-2 py-2 px-3 text-neutral-300 no-underline whitespace-nowrap transition-all duration-150 rounded-lg`};

            &:not(:first-of-type) {
                ${tw`ml-2`};
            }

            &:hover {
                ${tw`text-neutral-100 bg-neutral-700`};
            }

            &:active,
            &.active {
                ${tw`text-neutral-100 bg-neutral-700`};
                box-shadow: inset 0 -2px ${theme`colors.cyan.500`.toString()};
            }
        }
    }
`;

export default SubNavigation;
