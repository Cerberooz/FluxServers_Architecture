import React from 'react';
import { Link } from 'react-router-dom';
import { Formik } from 'formik';
import tw from 'twin.macro';
import LoginFormContainer from '@/components/auth/LoginFormContainer';

/**
 * LoginFormContainer renders Formik's <Form> element. Keep this simple
 * confirmation screen in a no-op Formik context so it does not attempt to
 * read Formik's reset handler from an undefined context.
 */
export default () => (
    <Formik initialValues={{}} onSubmit={() => undefined}>
        <LoginFormContainer title={'Email verified'} subtitle={'Your Fluid Panel account is active.'} css={tw`w-full flex`}>
            <div css={tw`rounded-lg border border-green-700 bg-green-900 bg-opacity-30 p-5 text-sm text-green-100`}>
                Your email address has been verified. You can now sign in to the panel.
            </div>
            <div css={tw`mt-6`}>
                <Link to={'/auth/login'} css={tw`block rounded bg-blue-600 px-4 py-3 text-center text-sm font-semibold text-white no-underline hover:bg-blue-500`}>
                    Continue to sign in
                </Link>
            </div>
        </LoginFormContainer>
    </Formik>
);
