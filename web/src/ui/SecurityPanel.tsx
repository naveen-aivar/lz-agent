import type { CheckStats, ValidationReport } from "../logic/reports";
import { CHECK_NAMES } from "../logic/reports";
import { when } from "../logic/format";
import { Kpi } from "./Kpi";
import { Badge } from "./Badge";
function Bar({ label, s }: { label: string; s?: CheckStats | null }) {
  if (!s) return <div className="barrow"><div className="lab">{label}<span>The scan produced no report</span></div></div>;
  const n = s.passed + s.failed + s.skipped;
  const pc = (x: number) => `${n ? (x / n) * 100 : 0}%`;
  return (
    <div className="barrow">
      <div className="lab">{label}<span>{n} checks: {s.passed} passed, {s.failed} failed{s.skipped ? `, ${s.skipped} skipped` : ""}</span></div>
      <div className="pbar" role="img" aria-label={`${s.passed} passed, ${s.failed} failed`}>
        <i className="g" style={{ width: pc(s.passed) }} /><i className="r" style={{ width: pc(s.failed) }} /><i className="k" style={{ width: pc(s.skipped) }} />
      </div>
    </div>
  );
}
export function SecurityPanel({ report: rep, onDownload }: { report: ValidationReport; onDownload: (name: "reports" | "report") => void }) {
  const t = rep.security.totals;
  const failed = (["terraform", "cloudformation"] as const).flatMap((f) => (rep.security[f]?.failedChecks ?? []).map((c) => ({ ...c, stack: f })));
  const ok = rep.overall === "pass";
  return (
    <div>
      <div className="row split">
        <Badge tone={ok ? "green" : "red"}>{ok ? "All validation checks passed" : "Validation failed"}</Badge>
        <span className="hint">Scanned {when(Date.parse(rep.generatedAt) / 1000)}</span>
      </div>
      <div className="grid-kpi">
        <Kpi label="Checks scanned" value={String(t.scanned)} />
        <Kpi label="Passed" value={String(t.passed)} tone="green" />
        <Kpi label="Failed" value={String(t.failed)} hint={t.failed ? "Listed below" : "None"} tone={t.failed ? "red" : ""} />
        <Kpi label="Skipped" value={String(t.skipped)} />
      </div>
      <section className="sec">
        <h3>Security scan <small>checkov</small></h3>
        <Bar label="Terraform" s={rep.security.terraform} /><Bar label="CloudFormation" s={rep.security.cloudformation} />
        <p className="hint">The security scan looks for risky configuration in the generated code. Findings are reported here and in the downloads but do not block delivery.</p>
        {failed.length > 0 && <ul className="failures">{failed.map((c) => (
          <li key={`${c.stack}:${c.id}:${c.resource}`}><b>{c.id}</b> {c.name}<small>{c.stack}: {c.resource}, {c.file}</small></li>))}</ul>}
      </section>
      <section className="sec">
        <h3>Validation <small>does the code work and follow best practice</small></h3>
        <ul className="checks">{rep.checks.map((c) => (
          <li key={c.name}><span className={c.result === "pass" ? "ok" : "no"}>{c.result === "pass" ? "✓" : "✕"}</span>{CHECK_NAMES[c.name] ?? c.name}</li>))}</ul>
        <p className="hint">Lint and validate check that the templates are well formed and follow best practice. They are separate from the security scan above.</p>
      </section>
      <div className="row"><button type="button" className="btn" onClick={() => onDownload("reports")}>Scan reports (zip)</button><button type="button" className="btn" onClick={() => onDownload("report")}>Validation report (JSON)</button></div>
    </div>
  );
}
