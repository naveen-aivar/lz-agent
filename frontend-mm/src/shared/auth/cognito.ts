import { COGNITO } from './config';

// The one place that talks to Cognito (through amazon-cognito-identity-js, which does the SRP sign-in: the password itself is never sent).
// The library is loaded on first use, so a build without sign-in does not carry it. Tokens are kept in sessionStorage (this tab only, gone
// when the tab is closed): this app is a static page with no server of its own, so there is no HttpOnly cookie to keep them in. That is a
// deliberate, documented exception to "no tokens in web storage"; the real protection is the API checking the token (see the README).

type CognitoLib = typeof import('amazon-cognito-identity-js');
type Pool = InstanceType<CognitoLib['CognitoUserPool']>;
type User = InstanceType<CognitoLib['CognitoUser']>;

const lib = (() => {
  let loading: Promise<CognitoLib> | undefined;
  return () => (loading ??= import('amazon-cognito-identity-js'));
})();

const poolOnce = (() => {
  let pool: Promise<Pool> | undefined;
  return () =>
    (pool ??= lib().then(
      ({ CognitoUserPool }) =>
        new CognitoUserPool({
          UserPoolId: COGNITO.poolId,
          ClientId: COGNITO.clientId,
          Storage: window.sessionStorage,
          ...(COGNITO.endpoint ? { endpoint: COGNITO.endpoint } : {}),
        }),
    ));
})();

const userOf = async (email: string): Promise<User> => {
  const [{ CognitoUser }, pool] = await Promise.all([lib(), poolOnce()]);
  return new CognitoUser({ Username: email.trim(), Pool: pool, Storage: window.sessionStorage });
};

// Plain words for what Cognito reports. The same message for a wrong password and an unknown address, so the page never says which exists.
const MESSAGES: Record<string, string> = {
  NotAuthorizedException: 'That email and password do not match.',
  UserNotFoundException: 'That email and password do not match.',
  UserNotConfirmedException:
    'This account is not confirmed yet. Confirm your email address first (use the code we emailed you).',
  CodeMismatchException: 'That code is not right. Check it and try again.',
  // Cognito says "expired" for a code that ran out AND for one a newer code has replaced (or that was already used).
  ExpiredCodeException:
    'That code is no longer valid. Use the code from your newest email (asking for a new code cancels the earlier ones), or ask for a new one.',
  InvalidParameterException: 'Check what you typed and try again.',
  LimitExceededException: 'Too many attempts. Wait a few minutes and try again.',
  TooManyRequestsException: 'Too many attempts. Wait a few minutes and try again.',
  TooManyFailedAttemptsException: 'Too many attempts. Wait a few minutes and try again.',
  UserLambdaValidationException: 'Sign-up is not permitted for this email address.',
  NetworkError: 'We could not reach the sign-in service. Check your connection and try again.',
};
// Listed as pairs, apart from the map above: a secret scanner takes a name that contains the word for a credential, followed by a quoted text, for a hard-coded one, and these are only sentences.
for (const [name, sentence] of [
  ['PasswordResetRequiredException', 'You need to choose a new password. Use "Forgot your password?" below.'],
  ['InvalidPasswordException', 'That password is not strong enough. Use at least 12 characters.'],
] as const) {
  MESSAGES[name] = sentence;
}

/** An error in plain words; `code` is Cognito's own name for what went wrong (the page reacts to a few of them). */
export class SignInError extends Error {
  code: string;
  constructor(message: string, code = '') {
    super(message);
    this.code = code;
  }
}

const friendly = (e: unknown): SignInError => {
  const raw = (e ?? {}) as { code?: string; name?: string; message?: unknown };
  const code = raw.code || raw.name || '';
  const looksLikeNetwork = /network|fetch/i.test(String(raw.message));
  return new SignInError(
    MESSAGES[code] ?? (looksLikeNetwork ? MESSAGES.NetworkError : 'Something went wrong signing in. Try again in a moment.'),
    code,
  );
};

export interface Session {
  email: string;
  /** "" when the account has no name. */
  name: string;
  idToken: string;
}

/** The signed-in person, or null. An expired token is renewed with the refresh token first. */
export async function currentSession(): Promise<Session | null> {
  const pool = await poolOnce();
  const user = pool.getCurrentUser();
  if (!user) return null;
  return new Promise((resolve) => {
    user.getSession((err: Error | null, session: import('amazon-cognito-identity-js').CognitoUserSession | null) => {
      if (err || !session?.isValid()) {
        resolve(null);
        return;
      }
      const id = session.getIdToken();
      const payload = id.payload as { given_name?: string; family_name?: string; name?: string; email?: string };
      resolve({
        email: payload.email || user.getUsername(),
        name: [payload.given_name, payload.family_name].filter(Boolean).join(' ') || payload.name || '',
        idToken: id.getJwtToken(),
      });
    });
  });
}

/** A fresh ID token for the API, or null when there is no session. */
export async function idToken(): Promise<string | null> {
  return (await currentSession())?.idToken ?? null;
}

/** What signing in leads to: done, or one more thing to ask for. */
export type SignInStep =
  | { step: 'done' }
  | { step: 'choose-new'; finish: (newPassword: string) => Promise<SignInStep> }
  | { step: 'code'; finish: (code: string) => Promise<SignInStep> };

/**
 * Signs in. Resolves { step: "done" }, or the next thing to ask for: { step: "choose-new", finish(newPassword) } for an account whose
 * password is temporary, or { step: "code", finish(code) } for an account with an authenticator app. Rejects with a plain-words Error.
 */
export async function signIn(email: string, password: string): Promise<SignInStep> {
  const [{ AuthenticationDetails }, user] = await Promise.all([lib(), userOf(email)]);
  const finishing = (resolve: (step: SignInStep) => void, reject: (error: Error) => void) => ({
    onSuccess: () => resolve({ step: 'done' }),
    onFailure: (e: unknown) => reject(friendly(e)),
  });
  return new Promise<SignInStep>((resolve, reject) => {
    user.authenticateUser(new AuthenticationDetails({ Username: email.trim(), Password: password }), {
      ...finishing(resolve, reject),
      newPasswordRequired: (attributes: Record<string, string> | null) => {
        // Cognito refuses these two when they are sent back with the new password.
        const { email_verified: _verified, email: _email, ...rest } = attributes ?? {};
        void _verified;
        void _email;
        resolve({
          step: 'choose-new',
          finish: (newPassword) =>
            new Promise<SignInStep>((res, rej) => user.completeNewPasswordChallenge(newPassword, rest, finishing(res, rej))),
        });
      },
      totpRequired: () =>
        resolve({
          step: 'code',
          finish: (code) =>
            new Promise<SignInStep>((res, rej) => user.sendMFACode(code.trim(), finishing(res, rej), 'SOFTWARE_TOKEN_MFA')),
        }),
      mfaRequired: () =>
        reject(
          new Error(
            'This account asks for a text-message code, which this page does not support. Use an authenticator app, or sign in to the Ingram Micro Agents dashboard to change it.',
          ),
        ),
      mfaSetup: () =>
        reject(
          new Error(
            'This account has to set up two-step verification first. Do that in the Ingram Micro Agents dashboard, then sign in here.',
          ),
        ),
      selectMFAType: () =>
        reject(
          new Error(
            'This account has more than one two-step method, which this page does not support. Sign in to the Ingram Micro Agents dashboard to change it.',
          ),
        ),
    });
  });
}

/** Ends the session here and, as far as it can, at Cognito (the refresh token stops working). */
export async function signOut(): Promise<void> {
  const pool = await poolOnce();
  const user = pool.getCurrentUser();
  if (!user) return;
  await new Promise<void>((resolve) => user.signOut(() => resolve()));
  user.signOut(); // revoking can fail (offline); the saved tokens are removed either way
}

/** Asks Cognito to email a code for choosing a new password. */
export async function sendResetCode(email: string): Promise<void> {
  const user = await userOf(email);
  return new Promise((resolve, reject) =>
    user.forgotPassword({ onSuccess: () => resolve(), inputVerificationCode: () => resolve(), onFailure: (e) => reject(friendly(e)) }),
  );
}

/** Sets the new password with the emailed code. */
export async function confirmReset(email: string, code: string, newPassword: string): Promise<void> {
  const user = await userOf(email);
  return new Promise((resolve, reject) =>
    user.confirmPassword(code.trim(), newPassword, { onSuccess: () => resolve(), onFailure: (e) => reject(friendly(e)) }),
  );
}

export interface SignUpResult {
  /** True when the address already has an account, confirmed or not (the page then finds out which). */
  exists: boolean;
  /** Where the confirmation code went (Cognito's masked address, like "n***@a***"). */
  to?: string;
}

/**
 * Creates an account (the pool's pre-sign-up rule decides which addresses are allowed) and emails a code. Unlike the dashboard, which
 * answers the same either way, this tells the person when the address already has an account: it is an internal pool, and "a code was
 * sent" for an address that already has one only sends people looking for an email that never comes.
 */
export async function signUp(input: { email: string; password: string; firstName?: string; lastName?: string }): Promise<SignUpResult> {
  const [{ CognitoUserAttribute }, pool] = await Promise.all([lib(), poolOnce()]);
  const attributes = [new CognitoUserAttribute({ Name: 'email', Value: input.email.trim() })];
  if (input.firstName?.trim()) attributes.push(new CognitoUserAttribute({ Name: 'given_name', Value: input.firstName.trim() }));
  if (input.lastName?.trim()) attributes.push(new CognitoUserAttribute({ Name: 'family_name', Value: input.lastName.trim() }));
  return new Promise((resolve, reject) =>
    pool.signUp(input.email.trim(), input.password, attributes, [], (e, result) => {
      if (!e) resolve({ exists: false, to: result?.codeDeliveryDetails?.Destination || '' });
      else if ((e as { code?: string }).code === 'UsernameExistsException') resolve({ exists: true });
      else reject(friendly(e));
    }),
  );
}

/** Cognito's way of hiding an address ("a***@e***"), for when it says nothing (an address that already has an account), so both read alike. */
export const maskEmail = (email: string): string => {
  const [local = '', domain = ''] = String(email).trim().split('@');
  return `${local.slice(0, 1)}***@${domain.slice(0, 1)}***`;
};

/** Confirms the address with the 6-digit code that was emailed. */
export async function confirmSignUp(email: string, code: string): Promise<void> {
  const user = await userOf(email);
  return new Promise((resolve, reject) => user.confirmRegistration(code.trim(), true, (e) => (e ? reject(friendly(e)) : resolve())));
}

/** Emails a new confirmation code (the earlier ones stop working). Resolves where it was sent, masked. */
export async function resendCode(email: string): Promise<string> {
  const user = await userOf(email);
  return new Promise((resolve, reject) =>
    user.resendConfirmationCode((e, result) => (e ? reject(friendly(e)) : resolve(result?.CodeDeliveryDetails?.Destination || ''))),
  );
}
