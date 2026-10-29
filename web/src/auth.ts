import type { Config } from "./config";

/** Cognito group allowed to answer and decide AWS Transform questions (platform.yaml TransformApproversGroup). */
export const APPROVER_GROUP = "transform-approvers";
const TOKEN_KEY = "idToken";
const PKCE_KEY = "pkce";

export interface Claims {
  sub?: string;
  email?: string;
  exp?: number;
  "cognito:groups"?: string[] | string;
}

const b64url = (buf: ArrayBuffer | Uint8Array): string =>
  btoa(String.fromCharCode(...new Uint8Array(buf as ArrayBuffer))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

/** The page Cognito sends the browser back to; listed in the user pool client's callback URLs. */
export const redirectUri = (): string => `${location.origin}/`;

export function decodeJwt(token: string): Claims {
  const payload = token.split(".")[1];
  if (!payload) throw new Error("not a JWT");
  return JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))) as Claims;
}

export const isExpired = (claims: Claims, nowMs = Date.now()): boolean => !claims.exp || claims.exp * 1000 < nowMs + 30_000;

/** cognito:groups arrives as an array or as a string such as "[a b]" depending on the token. */
export function groupsOf(claims: Claims): string[] {
  const g = claims["cognito:groups"];
  if (Array.isArray(g)) return g;
  if (typeof g === "string") return g.replace(/^\[|\]$/g, "").split(/[\s,]+/).filter(Boolean);
  return [];
}

export const canAnswerTransform = (claims: Claims): boolean => groupsOf(claims).includes(APPROVER_GROUP);

export function storedToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export async function login(cfg: Config): Promise<void> {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  sessionStorage.setItem(PKCE_KEY, verifier);
  const q = new URLSearchParams({
    response_type: "code", client_id: cfg.clientId, redirect_uri: redirectUri(), scope: "openid email",
    code_challenge_method: "S256", code_challenge: challenge,
  });
  location.href = `https://${cfg.cognitoDomain}/oauth2/authorize?${q}`;
}

export async function exchangeCode(cfg: Config, code: string): Promise<string> {
  const verifier = sessionStorage.getItem(PKCE_KEY);
  if (!verifier) throw new Error("sign-in was not started in this browser tab; sign in again");
  const body = new URLSearchParams({
    grant_type: "authorization_code", client_id: cfg.clientId, code, redirect_uri: redirectUri(), code_verifier: verifier,
  });
  const r = await fetch(`https://${cfg.cognitoDomain}/oauth2/token`, {
    method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body,
  });
  if (!r.ok) throw new Error(`sign-in failed (HTTP ${r.status})`);
  const t = (await r.json()) as { id_token?: string };
  if (!t.id_token) throw new Error("sign-in returned no id token");
  sessionStorage.setItem(TOKEN_KEY, t.id_token);
  sessionStorage.removeItem(PKCE_KEY);
  return t.id_token;
}

export function logout(cfg: Config): void {
  sessionStorage.clear();
  location.href = `https://${cfg.cognitoDomain}/logout?client_id=${cfg.clientId}&logout_uri=${encodeURIComponent(redirectUri())}`;
}
