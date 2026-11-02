import { useCallback, useState } from 'react';

import { refreshAuth } from './auth-store';
import {
  SignInError,
  confirmReset,
  confirmSignUp,
  maskEmail,
  resendCode,
  sendResetCode,
  signIn,
  signUp,
  type SignInStep,
} from './cognito';
import { MIN_PASSWORD, type LoginView } from './login-views';

/**
 * The sign-in page's steps (sign in, then a code for accounts with two-step verification or a new password for a temporary one; create an
 * account and confirm its email; reset a forgotten password) as state and actions, so the page itself is only markup.
 */
export function useLoginFlow() {
  const [view, setView] = useState<LoginView>('sign-in');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [pending, setPending] = useState<Exclude<SignInStep, { step: 'done' }> | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** Sign-up found that the address already has an account (Cognito does not say whether it was confirmed). */
  const [exists, setExists] = useState(false);

  const go = useCallback((next: LoginView, message: string | null = null) => {
    setView(next);
    setNotice(message);
    setError(null);
    setExists(false);
    setCode('');
    setNewPassword('');
  }, []);

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (e) {
      // An account whose email was never confirmed goes to the confirmation step, as in the dashboard.
      if (e instanceof SignInError && e.code === 'UserNotConfirmedException') {
        go('confirm', 'Confirm your email first: enter the code we sent you.');
      } else {
        setNotice(null); // a green "sent" note and a red error must never stand together
        setError(e instanceof Error ? e.message : 'Something went wrong signing in. Try again in a moment.');
      }
    } finally {
      setBusy(false);
    }
  };

  const step = async (result: SignInStep) => {
    if (result.step === 'done') {
      await refreshAuth();
      return;
    }
    setPending(result);
    go(result.step);
  };

  const refuseShort = (length: number) => {
    if (length >= MIN_PASSWORD) return false;
    setError(`Use at least ${MIN_PASSWORD} characters.`);
    return true;
  };

  const submit = () => {
    switch (view) {
      case 'sign-in':
        return run(async () => step(await signIn(email, password)));
      case 'choose-new':
        if (refuseShort(newPassword.length) || !pending) return;
        return run(async () => step(await pending.finish(newPassword)));
      case 'code':
        if (!pending) return;
        return run(async () => step(await pending.finish(code)));
      case 'sign-up':
        if (refuseShort(password.length)) return;
        return run(async () => {
          const made = await signUp({ email, password, firstName, lastName });
          if (made.exists) {
            setExists(true); // shown on this page, with what the person can do about it
            return;
          }
          go('confirm', `We sent a 6-digit code to ${made.to || maskEmail(email)}. Enter it to confirm your email.`);
        });
      case 'confirm':
        return run(async () => {
          await confirmSignUp(email, code);
          setPassword('');
          go('sign-in', 'Your email is confirmed. Sign in.');
        });
      case 'forgot':
        return run(async () => {
          await sendResetCode(email);
          go('reset', 'If that address has an account, we have sent a code to it.');
        });
      case 'reset':
        if (refuseShort(newPassword.length)) return;
        return run(async () => {
          await confirmReset(email, code, newPassword);
          setPassword('');
          go('sign-in', 'Your password was changed. Sign in with it.');
        });
    }
  };

  /** For an address that already has an account: Cognito sends a code only if that account was never confirmed, and answers the same either way. */
  const sendCodeForExisting = () =>
    run(async () => {
      const to = await resendCode(email);
      go(
        'confirm',
        `If that account was waiting to be confirmed, we sent a new code to ${to || maskEmail(email)}. If it was already confirmed, no code is sent: go back to sign in.`,
      );
    });

  const resend = () =>
    run(async () => {
      const to = await resendCode(email);
      setNotice(`We sent a new code to ${to || maskEmail(email)}. The earlier codes no longer work.`);
    });

  const canSubmit =
    view === 'sign-up'
      ? !!email.trim() && !!password
      : view === 'confirm'
        ? !!code.trim()
        : view === 'sign-in'
          ? !!email.trim() && !!password
          : view === 'forgot'
            ? !!email.trim()
            : view === 'code'
              ? !!code.trim()
              : view === 'reset'
                ? !!code.trim() && !!newPassword
                : !!newPassword;

  return {
    view, go, busy, notice, error, exists, canSubmit,
    email, setEmail: (value: string) => { setEmail(value); setExists(false); },
    password, setPassword, firstName, setFirstName, lastName, setLastName, code, setCode, newPassword, setNewPassword,
    submit, sendCodeForExisting, resend,
  };
}
