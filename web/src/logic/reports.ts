/** The two reports a finished run produces. Parsers name what is missing; a page shows that, never a blank. */
export interface CheckStats { passed: number; failed: number; skipped: number; failedChecks?: { id: string; name: string; resource: string; file: string }[] }

export interface ValidationReport {
  overall: string;
  generatedAt: string;
  security: { totals: { scanned: number; passed: number; failed: number; skipped: number }; terraform?: CheckStats | null; cloudformation?: CheckStats | null };
  checks: { name: string; result: string }[];
}

export interface DeploymentReport {
  overall: string;
  designRunId?: string;
  outcomeReasons?: string[];
  observed?: { preDeploy?: { ouCount: number; accountCount: number }; postDeploy?: { ouCount: number; accountCount: number } };
  classification?: { preDeploy?: string; postDeploy?: string };
  gaps?: { preDeploy?: Gaps; postDeploy?: Gaps };
  disclaimer?: string;
}
export interface Gaps { missingOus?: string[]; missingAccountsByName?: string[] }

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

export function parseValidationReport(raw: unknown): ValidationReport {
  if (!isObj(raw) || typeof raw.overall !== "string" || !isObj(raw.security) || !isObj((raw.security as Record<string, unknown>).totals) || !Array.isArray(raw.checks)) {
    throw new Error("the validation report is missing overall, security.totals or checks");
  }
  return raw as unknown as ValidationReport;
}

export function parseDeploymentReport(raw: unknown): DeploymentReport {
  if (!isObj(raw) || typeof raw.overall !== "string") throw new Error("the deployment report has no overall result");
  return raw as unknown as DeploymentReport;
}

export const CHECK_NAMES: Record<string, string> = {
  "tf-fmt": "Terraform format", "tf-init": "Terraform init", "tf-validate": "Terraform validate", "tf-lint": "Terraform lint",
  "tf-security": "Terraform security scan", "cfn-lint": "CloudFormation lint", "cfn-security": "CloudFormation security scan",
};

export const DEPLOY_OVERALL: Record<string, ["green" | "amber" | "red" | "muted", string]> = {
  pass: ["green", "Foundation attestation passed"],
  pass_with_manual_steps: ["amber", "Passed with manual steps"],
  fail: ["red", "Attestation failed"],
};

export function gapSummary(g?: Gaps): string {
  if (!g) return "None listed";
  const parts: string[] = [];
  if (g.missingOus?.length) parts.push(`${g.missingOus.length} missing OU(s)`);
  if (g.missingAccountsByName?.length) parts.push(`${g.missingAccountsByName.length} missing account name(s)`);
  return parts.length ? parts.join(", ") : "No missing OUs or account names vs scope";
}
