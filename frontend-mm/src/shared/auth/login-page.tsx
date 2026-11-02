'use client';

import { useEffect, type ReactNode } from 'react';

import { AivarLogo } from '@/shared/components/aivar-logo';
import { FieldLabel, TextInput } from '@/shared/components/form-controls';
import { IngramLogo } from '@/shared/components/ingram-logo';
import { Notice } from '@/shared/components/notice';
import { Button } from '@/shared/design-system/ui/button';
import { Skeleton, SkeletonText } from '@/shared/design-system/ui/skeleton';

import { APP_NAME, LOGIN_COPY } from './config';
import { LEADS, MIN_PASSWORD, SUBMIT_LABELS, TITLES } from './login-views';
import { SilkWaves } from './silk-waves';
import { useLoginFlow } from './use-login-flow';

const LINK =
  'cursor-pointer font-semibold text-[var(--color-primary-700)] underline underline-offset-2 hover:text-[var(--color-primary-hover)] disabled:cursor-not-allowed disabled:opacity-50';

function Field({ id, label, hint, optional, children }: { id: string; label: string; hint?: string; optional?: boolean; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <FieldLabel htmlFor={id} label={label} hint={hint} optional={optional} />
      {children}
    </div>
  );
}

/**
 * The sign-in page: the form on the left, the blue silk-waves panel on the right (the unified dashboard's login). While the page is still
 * looking for a session kept in this tab (`checking`) it draws the shape of the form, so nothing jumps when the answer arrives.
 */
export function LoginPage({ checking = false }: { checking?: boolean }) {
  const flow = useLoginFlow();
  const { view, busy, notice, error, exists } = flow;

  useEffect(() => {
    document.title = `Sign in | ${APP_NAME} | Ingram Micro`;
  }, []);

  const showEmail = view === 'sign-in' || view === 'sign-up' || view === 'forgot' || view === 'reset';
  const showPassword = view === 'sign-in' || view === 'sign-up';
  const showCode = view === 'code' || view === 'reset' || view === 'confirm';
  const showNew = view === 'choose-new' || view === 'reset';

  return (
    <div className="flex min-h-dvh bg-[var(--color-gray-25)]">
      <main className="flex flex-1 items-center justify-center px-6 py-12 sm:px-12 lg:basis-1/2 lg:flex-none lg:px-20">
        <div className="w-full max-w-sm">
          {/* The logo brings its own clear space as padding; the negative margins keep the artwork flush with the form below. */}
          <IngramLogo size="md" className="-mt-[var(--logo-clear-space)] -ml-[var(--logo-clear-space)]" />
          <h1 className="mt-3 text-2xl font-bold text-[var(--color-gray-900)]">{TITLES[view]}</h1>
          {LEADS[view] ? <p className="mt-2 leading-6 text-[var(--color-gray-600)]">{LEADS[view]}</p> : null}

          {checking ? (
            <div role="status" aria-busy="true" aria-label="Checking whether you are already signed in" className="mt-8 flex flex-col gap-5">
              <div className="space-y-1.5">
                <SkeletonText>Email address</SkeletonText>
                <Skeleton className="h-[2.625rem]" />
              </div>
              <div className="space-y-1.5">
                <SkeletonText>Password</SkeletonText>
                <Skeleton className="h-[2.625rem]" />
              </div>
              <Skeleton className="h-[2.875rem] rounded-[var(--radius-pill)]" />
            </div>
          ) : (
            <form
              className="mt-8 flex flex-col gap-5"
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                void flow.submit();
              }}
            >
              {notice ? <Notice tone="success">{notice}</Notice> : null}
              {view === 'sign-up' && exists ? (
                <Notice tone="warning" title="That email already has an account.">
                  Sign in with it, or choose “Forgot your password?” if you do not remember the password. If you started creating it but never
                  confirmed it, we can send you a new code.
                  <span className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
                    <button type="button" className={LINK} onClick={() => flow.go('sign-in')}>
                      Go to sign in
                    </button>
                    <button type="button" className={LINK} disabled={busy} onClick={() => void flow.sendCodeForExisting()}>
                      Send me a confirmation code
                    </button>
                  </span>
                </Notice>
              ) : null}
              {error ? <Notice tone="danger">{error}</Notice> : null}

              {view === 'sign-up' ? (
                <div className="grid grid-cols-1 gap-3 min-[400px]:grid-cols-2">
                  <Field id="login-first" label="First name" optional>
                    <TextInput id="login-first" autoComplete="given-name" maxLength={80} value={flow.firstName} onChange={(e) => flow.setFirstName(e.target.value)} />
                  </Field>
                  <Field id="login-last" label="Last name" optional>
                    <TextInput id="login-last" autoComplete="family-name" maxLength={80} value={flow.lastName} onChange={(e) => flow.setLastName(e.target.value)} />
                  </Field>
                </div>
              ) : null}
              {showEmail ? (
                <Field id="login-email" label={view === 'sign-up' ? 'Work email' : 'Email address'}>
                  <TextInput
                    id="login-email"
                    type="email"
                    autoComplete="username"
                    required
                    autoFocus={view !== 'reset'}
                    readOnly={view === 'reset'}
                    value={flow.email}
                    onChange={(e) => flow.setEmail(e.target.value)}
                  />
                </Field>
              ) : null}
              {showPassword ? (
                <Field id="login-password" label="Password" hint={view === 'sign-up' ? `At least ${MIN_PASSWORD} characters.` : undefined}>
                  <TextInput
                    id="login-password"
                    type="password"
                    autoComplete={view === 'sign-up' ? 'new-password' : 'current-password'}
                    required
                    value={flow.password}
                    onChange={(e) => flow.setPassword(e.target.value)}
                  />
                </Field>
              ) : null}
              {showCode ? (
                <Field
                  id="login-code"
                  label={view === 'code' ? '6-digit code' : view === 'confirm' ? 'Confirmation code' : 'Code from the email'}
                  hint={view === 'confirm' || view === 'reset' ? 'Use the newest code. Asking for a new one cancels the earlier ones.' : undefined}
                >
                  <TextInput id="login-code" inputMode="numeric" autoComplete="one-time-code" required autoFocus value={flow.code} onChange={(e) => flow.setCode(e.target.value)} />
                </Field>
              ) : null}
              {showNew ? (
                <Field id="login-new" label="New password" hint={`At least ${MIN_PASSWORD} characters.`}>
                  <TextInput
                    id="login-new"
                    type="password"
                    autoComplete="new-password"
                    required
                    autoFocus={view === 'choose-new'}
                    value={flow.newPassword}
                    onChange={(e) => flow.setNewPassword(e.target.value)}
                  />
                </Field>
              ) : null}
              <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!flow.canSubmit}>
                {SUBMIT_LABELS[view]}
              </Button>
            </form>
          )}

          {checking ? (
            <div aria-hidden className="mt-5 text-sm">
              <SkeletonText>Forgot your password?</SkeletonText>
            </div>
          ) : (
            <div className="mt-5 flex flex-wrap justify-between gap-x-4 gap-y-2 text-sm">
              {view === 'sign-in' ? (
                <button type="button" className={LINK} onClick={() => flow.go('forgot')}>
                  Forgot your password?
                </button>
              ) : (
                <button type="button" className={LINK} onClick={() => flow.go('sign-in')}>
                  Back to sign in
                </button>
              )}
              {view === 'sign-in' ? (
                <button type="button" className={LINK} onClick={() => flow.go('sign-up')}>
                  Create an account
                </button>
              ) : null}
              {view === 'confirm' ? (
                <button type="button" className={LINK} disabled={busy || !flow.email.trim()} onClick={() => void flow.resend()}>
                  Send a new code
                </button>
              ) : null}
            </div>
          )}

          <div className="mt-8 flex items-center gap-2 text-xs text-[var(--color-gray-600)]">
            <span>Powered by</span>
            <AivarLogo className="h-4 w-auto text-[var(--color-gray-700)]" />
          </div>
        </div>
      </main>

      <aside aria-label="About WAFR Review" className="relative hidden basis-1/2 items-center justify-center overflow-hidden bg-[var(--color-primary-50)] lg:flex">
        <SilkWaves />
        <div className="relative z-[1] max-w-md px-10 text-center">
          <p className="font-display text-[2rem] leading-[1.2] font-bold tracking-[-0.03em] text-[var(--color-gray-900)]">{LOGIN_COPY.headline}</p>
          <p className="mt-4 text-sm text-[var(--color-gray-600)]">{LOGIN_COPY.tagline}</p>
        </div>
      </aside>
    </div>
  );
}
