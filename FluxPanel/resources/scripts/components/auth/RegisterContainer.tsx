import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Formik, FormikHelpers } from 'formik';
import { object, string, ref as yupRef } from 'yup';
import Reaptcha from 'reaptcha';
import tw from 'twin.macro';
import { useStoreState } from 'easy-peasy';
import register from '@/api/auth/register';
import Field from '@/components/elements/Field';
import Button from '@/components/elements/Button';
import LoginFormContainer from '@/components/auth/LoginFormContainer';
import useFlash from '@/plugins/useFlash';

interface Values {
    email: string;
    username: string;
    nameFirst: string;
    nameLast: string;
    password: string;
    passwordConfirmation: string;
}

const RegisterContainer = () => {
    const ref = useRef<Reaptcha>(null);
    const [token, setToken] = useState('');

    const { clearFlashes, clearAndAddHttpError } = useFlash();
    const { enabled: recaptchaEnabled, siteKey } = useStoreState((state) => state.settings.data!.recaptcha);

    useEffect(() => {
        clearFlashes();
    }, []);

    const onSubmit = (values: Values, { setSubmitting }: FormikHelpers<Values>) => {
        clearFlashes();

        if (recaptchaEnabled && !token) {
            ref.current!.execute().catch((error) => {
                console.error(error);

                setSubmitting(false);
                clearAndAddHttpError({ error });
            });

            return;
        }

        register({ ...values, recaptchaData: token })
            .then((response) => {
                // @ts-expect-error this is valid
                window.location = response.intended || '/';
            })
            .catch((error) => {
                console.error(error);

                setToken('');
                if (ref.current) ref.current.reset();

                setSubmitting(false);
                clearAndAddHttpError({ error });
            });
    };

    return (
        <Formik
            onSubmit={onSubmit}
            initialValues={{
                email: '',
                username: '',
                nameFirst: '',
                nameLast: '',
                password: '',
                passwordConfirmation: '',
            }}
            validationSchema={object().shape({
                email: string()
                    .email('A valid email address must be provided.')
                    .required('A valid email address must be provided.'),
                username: string().required('A username must be provided.'),
                nameFirst: string().required('A first name must be provided.'),
                nameLast: string().required('A last name must be provided.'),
                password: string().min(8, 'Password must be at least 8 characters.').required('A password is required.'),
                passwordConfirmation: string()
                    .oneOf([yupRef('password'), null], 'Passwords do not match.')
                    .required('Please confirm your password.'),
            })}
        >
            {({ isSubmitting, setSubmitting, submitForm }) => (
                <LoginFormContainer
                    title={'Create Your Account'}
                    subtitle={'Register to start managing your servers.'}
                    css={tw`w-full flex`}
                >
                    <Field type={'email'} label={'Email'} name={'email'} placeholder={'you@example.com'} autoComplete={'email'} disabled={isSubmitting} />
                    <div css={tw`mt-6`}>
                        <Field type={'text'} label={'Username'} name={'username'} placeholder={'Choose a username'} autoComplete={'username'} disabled={isSubmitting} />
                    </div>
                    <div css={tw`grid grid-cols-1 sm:grid-cols-2 gap-6 mt-6`}>
                        <Field type={'text'} label={'First Name'} name={'nameFirst'} placeholder={'First name'} autoComplete={'given-name'} disabled={isSubmitting} />
                        <Field type={'text'} label={'Last Name'} name={'nameLast'} placeholder={'Last name'} autoComplete={'family-name'} disabled={isSubmitting} />
                    </div>
                    <div css={tw`mt-6`}>
                        <Field type={'password'} label={'Password'} name={'password'} placeholder={'At least 8 characters'} autoComplete={'new-password'} disabled={isSubmitting} />
                    </div>
                    <div css={tw`mt-6`}>
                        <Field
                            type={'password'}
                            label={'Confirm Password'}
                            name={'passwordConfirmation'}
                            placeholder={'Repeat your password'}
                            autoComplete={'new-password'}
                            disabled={isSubmitting}
                        />
                    </div>
                    <div css={tw`mt-6`}>
                        <Button type={'submit'} size={'xlarge'} isLoading={isSubmitting} disabled={isSubmitting}>
                            Register
                        </Button>
                    </div>
                    {recaptchaEnabled && (
                        <Reaptcha
                            ref={ref}
                            size={'invisible'}
                            sitekey={siteKey || '_invalid_key'}
                            onVerify={(response) => {
                                setToken(response);
                                submitForm();
                            }}
                            onExpire={() => {
                                setSubmitting(false);
                                setToken('');
                            }}
                        />
                    )}
                    <div css={tw`mt-6 text-center`}>
                        <Link
                            to={'/auth/login'}
                            css={tw`text-xs text-neutral-500 tracking-wide no-underline uppercase hover:text-neutral-600`}
                        >
                            Already have an account?
                        </Link>
                    </div>
                </LoginFormContainer>
            )}
        </Formik>
    );
};

export default RegisterContainer;
