import { APP_NAME } from './config';

/** The pool's own rule (the pool is the authority; this only saves a round trip). */
export const MIN_PASSWORD = 12;

export type LoginView = 'sign-in' | 'choose-new' | 'code' | 'forgot' | 'reset' | 'sign-up' | 'confirm';

export const TITLES: Record<LoginView, string> = {
  'sign-in': `Sign in to ${APP_NAME}`,
  'choose-new': 'Choose a new password',
  code: 'Two-step verification',
  forgot: 'Reset your password',
  reset: 'Choose a new password',
  'sign-up': 'Create your account',
  confirm: 'Confirm your email',
};

export const LEADS: Partial<Record<LoginView, string>> = {
  'choose-new': 'Your password was set for you. Choose one of your own to continue.',
  code: 'Enter the 6-digit code from your authenticator app.',
  forgot: 'Enter your email address and we will send you a code.',
  reset: 'Enter the code we emailed you and choose a new password.',
  'sign-up': 'Use your work email. We will send you a code to confirm it.',
};

export const SUBMIT_LABELS: Record<LoginView, string> = {
  'sign-up': 'Create account',
  confirm: 'Confirm email',
  'sign-in': 'Sign in',
  'choose-new': 'Continue',
  code: 'Verify',
  forgot: 'Send the code',
  reset: 'Change password',
};
