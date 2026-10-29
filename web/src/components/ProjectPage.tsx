import { useCallback, useEffect, useState } from "react";
import type { ArtifactName, AuditItem, Client, Run } from "../api/client";
import { allActivity } from "../logic/activity";
import { parseScope } from "../logic/design";
import type { Scope } from "../logic/design";
import { isDone, pretty, stateOf } from "../logic/format";
import { journey, stepOrDefault } from "../logic/journey";
import type { StepId } from "../logic/journey";
import { parseValidationReport } from "../logic/reports";
import type { ValidationReport } from "../logic/reports";
import { designSteps } from "../logic/steps";
import type { Theme } from "../theme";
import { Badge } from "../ui/Badge";
import { Kpi } from "../ui/Kpi";
import { OrgDiagram } from "../ui/OrgDiagram";
import { ScopePanel } from "../ui/ScopePanel";
import { ScpEditor } from "../ui/ScpEditor";
import { SecurityPanel } from "../ui/SecurityPanel";
import { Stepper } from "../ui/Stepper";
import { useToast } from "../ui/Toasts";
import { useDownload } from "../ui/useDownload";
import { AuditFeed } from "./AuditFeed";
import { DeployForm } from "./DeployForm";
import { Progress } from "./Progress";
import { RunPage } from "./RunPage";
const msg = (e: unknown): string => (e instanceof Error ? e.message : String(e));
const hasArtifact = (run: Run, k: string): boolean => !!(run.artifacts && (run.artifacts as Record<string, unknown>)[k]);
interface Loaded { scope: Scope; diagram: string; sha: string }
interface DeployRef { id: string; status: string }
/** One customer's project: analyze the SOW, review the design, edit the policies, deploy, see the results. Each step is one screen. */
export function ProjectPage({ designId, api, canAnswer, userSub, step, onStep, onCrumb, theme = "dark", pollMs = 4000 }: {
  designId: string; api: Client; canAnswer: boolean; userSub: string; theme?: Theme; pollMs?: number;
  /** The step in the address, or null to start where the project is. */
  step: string | null;
  onStep: (id: StepId) => void;
  onCrumb?: (name: string) => void;
}) {
  const toast = useToast();
  const download = useDownload(api);
  const [run, setRun] = useState<Run | null>(null);
  const [audit, setAudit] = useState<AuditItem[]>([]);
  const [design, setDesign] = useState<Loaded | null>(null);
  const [designError, setDesignError] = useState("");
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [reportError, setReportError] = useState("");
  const [deploy, setDeploy] = useState<DeployRef | null | undefined>(undefined);  // undefined: still looking
  const [again, setAgain] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const load = useCallback(async () => {
    try {
      const [r, a] = await Promise.all([api.getRun(designId), api.getAudit(designId)]);
      setRun(r.run); setAudit(a.audit); setError(""); setStale(false);
    } catch (e) {
      setError(msg(e)); setStale(true);
    }
  }, [api, designId]);
  useEffect(() => { setRun(null); setDesign(null); setReport(null); setDeploy(undefined); void load(); }, [load]);
  useEffect(() => {
    if (!run || isDone(run.status)) return;
    const t = setInterval(() => void load(), pollMs);
    return () => clearInterval(t);
  }, [run, load, pollMs]);
  // The newest deploy run built from this design.
  useEffect(() => {
    api.listRuns().then((r) => {
      const mine = r.runs.filter((x) => x.runKind === "deploy" && x.designRunId === designId).sort((a, b) => b.createdAt - a.createdAt)[0];
      setDeploy(mine ? { id: mine.runId, status: mine.status } : null);
    }).catch((e: unknown) => setError(msg(e)));
  }, [api, designId]);
  const ready = !!run && (isDone(run.status) || audit.some((a) => a.action === "phase.completed"));
  useEffect(() => {
    if (!ready || design) return;
    api.getScope(designId)
      .then((d) => { setDesign({ scope: parseScope(d.scope), diagram: d.orgDiagram, sha: d.sha }); setDesignError(""); })
      .catch((e: unknown) => setDesignError(msg(e)));
  }, [api, designId, ready, design]);
  const hasReport = !!run && hasArtifact(run, "report");
  useEffect(() => {
    if (!hasReport || report) return;
    api.getReportSummary(designId)
      .then((d) => { setReport(parseValidationReport(d.report)); setReportError(""); })
      .catch((e: unknown) => setReportError(msg(e)));
  }, [api, designId, hasReport, report]);
  const name = design?.scope.customer.orgName ?? (run ? pretty(run.customerId) || run.runId.slice(0, 8) : "");
  useEffect(() => { if (name) onCrumb?.(name); }, [name, onCrumb]);
  const onDeployLoaded = useCallback((r: Run) => setDeploy((d) => (d && d.id === r.runId && d.status === r.status ? d : { id: r.runId, status: r.status })), []);
  if (!run || deploy === undefined) return <p className="empty">{error || "Loading…"}</p>;
  const policies = design?.scope.customScps ?? [];
  const input = { designStatus: run.status, hasPolicies: policies.length > 0, deployStatus: deploy?.status ?? null };
  const current = stepOrDefault(step, input);
  const steps = journey(input, current);
  const idx = steps.findIndex((s) => s.id === current);
  const nextStep = steps[idx + 1];
  const [tone, label] = stateOf(run.status);
  const delivered = run.status === "DELIVERED";
  const next = (text?: string) => nextStep && (
    <div className="row next"><button type="button" className="btn btn-primary" disabled={!nextStep.open} onClick={() => onStep(nextStep.id)}>{text ?? `Next: ${nextStep.label}`}</button></div>
  );
  const dl = (k: ArtifactName, text: string, primary = false) => (
    <button type="button" className={`btn ${primary ? "btn-primary" : ""}`} disabled={!(k === "reports" ? hasArtifact(run, k) : delivered && hasArtifact(run, k))} onClick={() => void download(designId, k)}>{text}</button>
  );
  const sc = design?.scope;
  const missing = sc?.missingRequired ?? [];
  const questions = sc?.openQuestions.length ?? 0;
  return (
    <div className="run project">
      <div className="crumbs"><a href="#/runs">← Projects</a></div>
      <h1 className="page-title">
        {name} {!isDone(run.status) && <span className={`live${stale ? " stale" : ""}`} role="status"><i aria-hidden="true" />{stale ? "Reconnecting…" : "Live"}</span>}
      </h1>
      <p className="page-sub">Follow the steps from left to right. You can come back to any step you have already reached.</p>
      <Stepper steps={steps} onGo={onStep} />
      {error && !stale && <p className="errtext" role="alert">{error}</p>}
      {designError && <p className="errtext" role="alert">The design could not be shown: {designError}</p>}

      {current === "analyze" && (
        <div className="panel panel-pad">
          <div className="card-head"><h2>{delivered ? "Your design is ready" : run.status === "FAILED" ? "The analysis stopped" : <><span className="spin" /> The agent is reading the SOW</>}</h2><Badge tone={tone}>{label}</Badge></div>
          <Progress steps={designSteps(run, audit)} />
          {run.status === "RUNNING" || run.status === "AWAITING_INPUT" ? <p className="hint">This usually takes a few minutes. You can leave this page: the analysis continues and the project stays under Projects.</p> : null}
          {run.status === "FAILED" && (
            <div className="notice notice-err" role="alert"><strong>This run failed.</strong> {run.error || "No reason was recorded."}<br />A failed analysis can't be resumed. <a href="#/new">Start a new project</a> with the same SOW.</div>
          )}
          {delivered && next("Review the design")}
        </div>
      )}

      {current === "review" && sc && design && (
        <>
          <div className="grid-kpi">
            <Kpi label="OUs" value={String(sc.summary.ous)} /><Kpi label="Accounts" value={String(sc.summary.accounts)} />
            <Kpi label="Controls enabled" value={String(sc.summary.controlAttachments)} /><Kpi label="Catalog SCPs" value={String(sc.summary.scps)} />
            <Kpi label="Custom SCPs" value={String(sc.summary.customScps ?? 0)} hint={policies.length ? "to review next" : undefined} tone={sc.summary.customScps ? "amber" : ""} />
          </div>
          {(missing.length > 0 || questions > 0) && (
            <div className="card">
              <div className="card-head"><h2>Before you apply the code</h2></div>
              {missing.length > 0 && (<>
                <ul className="todo">{missing.map((n) => <li key={n}><b>!</b><span>{n[0]!.toUpperCase() + n.slice(1)}</span></li>)}</ul>
                <p className="hint">Each account needs a unique root email that has never been used for another AWS account. Terraform reads them from <code>terraform.tfvars</code>, CloudFormation from the parameter files.</p>
              </>)}
              {questions > 0 && <p>{questions} open question{questions === 1 ? "" : "s"} to confirm with the customer are listed under Scope below.</p>}
            </div>
          )}
          <div className="panel panel-pad">
            <div className="card-head"><h2>Organization</h2></div>
            <OrgDiagram source={design.diagram} theme={theme} />
          </div>
          <details className="panel panel-pad fold"><summary>Scope in detail</summary><ScopePanel scope={sc} /></details>
          {report ? (
            <details className="panel panel-pad fold"><summary>Security and validation: {report.overall === "pass" ? "all checks passed" : "failed"}</summary>
              <SecurityPanel report={report} onDownload={(n) => void download(designId, n)} /></details>
          ) : reportError && <p className="errtext" role="alert">The validation report could not be shown: {reportError}</p>}
          <div className="card">
            <div className="card-head"><h2>Download the code</h2></div>
            <div className="row">{dl("terraform", "Terraform", true)}{dl("cloudformation", "CloudFormation")}{dl("reports", "Scan reports")}</div>
            <p className="hint">Each zip includes the docs, the custom SCPs, and its own scan reports. You can also deploy it here with AWS Transform.</p>
          </div>
          {next()}
        </>
      )}

      {current === "policies" && sc && design && (
        <div className="panel panel-pad">
          <div className="card-head"><h2>Edit the policies</h2></div>
          <ScpEditor runId={designId} scope={sc} sha={design.sha} api={api} nextLabel={`Next: ${nextStep?.label ?? "Deploy"}`}
            onNext={nextStep ? () => onStep(nextStep.id) : undefined}
            onSaved={(scope, sha, raw) => setDesign({ scope, sha, diagram: (raw as { orgDiagram: string }).orgDiagram })} />
        </div>
      )}

      {current === "deploy" && (
        <>
          {policies.some((p) => p.inputs.some((i) => !i.value)) && (
            <div className="notice notice-info">Some custom policies still have placeholders. They are not part of the deploy: they ship in <code>custom-scps/</code> in your downloads.
              {" "}<button type="button" className="btn-link" onClick={() => onStep("policies")}>Fill them in</button></div>
          )}
          {deploy && !again ? (
            <>
              <RunPage runId={deploy.id} api={api} canAnswer={canAnswer} userSub={userSub} theme={theme} embedded pollMs={pollMs} onLoaded={onDeployLoaded} />
              {deploy.status === "DELIVERED" && next("See the results")}
              {deploy.status === "FAILED" && <div className="row"><button type="button" className="btn btn-sm" onClick={() => setAgain(true)}>Start a new deploy instead</button></div>}
            </>
          ) : (
            <DeployForm designRunId={designId} api={api} onStarted={(id) => { setDeploy({ id, status: "RUNNING" }); setAgain(false); toast("Deploy started"); }} />
          )}
        </>
      )}

      {current === "done" && deploy && (
        <>
          <div className="notice notice-ok" role="status"><strong>The landing zone is built.</strong> Here is what was deployed and what to download.</div>
          <RunPage runId={deploy.id} api={api} canAnswer={canAnswer} userSub={userSub} theme={theme} embedded view="results" pollMs={pollMs} />
          <div className="card"><div className="card-head"><h2>The code you reviewed</h2></div><div className="row">{dl("terraform", "Terraform")}{dl("cloudformation", "CloudFormation")}</div></div>
        </>
      )}

      <details className="panel panel-pad fold">
        <summary>History of the analysis</summary>
        <AuditFeed audit={allActivity(audit, false)} userSub={userSub} />
      </details>
    </div>
  );
}
