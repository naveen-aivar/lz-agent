// Sign-in settings. Sign-in is ON only when both ids are set at build time (NEXT_PUBLIC_COGNITO_USER_POOL_ID and
// NEXT_PUBLIC_COGNITO_APP_CLIENT_ID). The pool is the one the unified Ingram Micro Agents dashboard uses, so one account works in every
// agent. The client id must belong to a PUBLIC app client (no secret) of that pool: a browser cannot keep a secret. None of these values
// is a secret. The variables are read as written (process.env.NEXT_PUBLIC_...) because Next replaces only that exact form at build time.
export const COGNITO = {
  poolId: process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID ?? '',
  clientId: process.env.NEXT_PUBLIC_COGNITO_APP_CLIENT_ID ?? '',
  // Only for a local test server that speaks Cognito's API; never set in a deployed build.
  endpoint: process.env.NEXT_PUBLIC_COGNITO_ENDPOINT || undefined,
};

export const authEnabled = Boolean(COGNITO.poolId && COGNITO.clientId);

/** The name on the sign-in page. */
export const APP_NAME = 'Migration and Modernization Agents';

export const LOGIN_COPY = {
  headline: 'Every migration agent, one sign-in.',
  tagline:
    'From the first assessment and the 7 Rs to the cost comparison, the landing zone and the migration launch. Sign in once, then switch between agents from the sidebar.',
};
