/** The approved design (scope.json) as the pages use it. `parseScope` names what is missing instead of crashing a page. */
export type Basis = "explicit" | "inferred" | string;

export interface Scope {
  customer: { orgName: string };
  regions: { home: string; governed: string[]; extraAllowed: string[]; denied: string[]; enforceDeny: boolean };
  logging: { retentionDays: number; accessLogRetentionDays: number; logArchiveAccountId?: string | null; auditAccountId?: string | null; kmsKeyArn?: string | null };
  ous: { name: string; parent?: string | null; basis?: Basis }[];
  accounts: { name: string; kind: string; ou: string; provisioning?: string; basis?: Basis }[];
  scps: { id: string; targets: string[]; basis?: Basis }[];
  controls: { id: string; targets: string[]; basis?: Basis }[];
  customScps: CustomScp[];
  unsupported: { requirement: string; reason: string }[];
  assumptions: string[];
  openQuestions: string[];
  missingRequired: string[];
  summary: { ous: number; accounts: number; controls: number; controlAttachments: number; scps: number; customScps?: number };
}

export interface CustomScp {
  id: string; title: string; description?: string; targets: string[]; basis?: Basis;
  inputs: { name: string; description: string }[]; warnings: string[]; policy: { Statement?: unknown[] } & Record<string, unknown>;
}

const need = (cond: boolean, what: string): void => {
  if (!cond) throw new Error(`the approved design is missing ${what}`);
};
const isArr = (v: unknown): v is unknown[] => Array.isArray(v);
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

export function parseScope(raw: unknown): Scope {
  need(isObj(raw), "its content");
  const s = raw as Record<string, unknown>;
  need(isObj(s.customer) && typeof (s.customer as Record<string, unknown>).orgName === "string", "customer.orgName");
  need(isObj(s.regions) && typeof (s.regions as Record<string, unknown>).home === "string", "regions.home");
  const r = s.regions as Record<string, unknown>;
  for (const k of ["governed", "extraAllowed", "denied"]) need(isArr(r[k]), `regions.${k}`);
  need(isObj(s.logging), "logging");
  need(isObj(s.summary), "summary");
  for (const k of ["ous", "scps", "controls", "unsupported", "assumptions", "openQuestions"]) need(isArr(s[k]), k);
  need(s.accounts === undefined || isArr(s.accounts), "accounts");
  need(s.customScps === undefined || isArr(s.customScps), "customScps");
  need(s.missingRequired === undefined || isArr(s.missingRequired), "missingRequired");
  return { ...s, accounts: s.accounts ?? [], customScps: s.customScps ?? [], missingRequired: s.missingRequired ?? [] } as unknown as Scope;
}
