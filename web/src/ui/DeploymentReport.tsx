import type { DeploymentReport as Report } from "../logic/reports";
import { DEPLOY_OVERALL, gapSummary } from "../logic/reports";
import { Badge } from "./Badge";
import { Kpi } from "./Kpi";
export function DeploymentReport({ report: rep, onDownload }: { report: Report; onDownload: () => void }) {
  const [tone, label] = DEPLOY_OVERALL[rep.overall] ?? ["muted", rep.overall];
  const pre = rep.observed?.preDeploy, post = rep.observed?.postDeploy;
  const n = (v?: number) => (v === undefined ? "–" : String(v));
  return (
    <div>
      <div className="row split"><Badge tone={tone}>{label}</Badge>{rep.designRunId && <span className="hint">Design run <code>{rep.designRunId.slice(0, 8)}</code></span>}</div>
      {rep.outcomeReasons?.length ? <ul className="bullets">{rep.outcomeReasons.map((r) => <li key={r}>{r}</li>)}</ul> : null}
      <div className="grid-kpi">
        <Kpi label="Pre-deploy OUs" value={n(pre?.ouCount)} /><Kpi label="Post-deploy OUs" value={n(post?.ouCount)} />
        <Kpi label="Pre-deploy accounts" value={n(pre?.accountCount)} /><Kpi label="Post-deploy accounts" value={n(post?.accountCount)} />
      </div>
      <section className="sec"><h3>Classification</h3>
        <dl className="kv"><dt>Before deploy</dt><dd>{rep.classification?.preDeploy ?? "–"}</dd><dt>After deploy</dt><dd>{rep.classification?.postDeploy ?? "–"}</dd></dl></section>
      <section className="sec"><h3>Gaps vs approved scope</h3>
        <dl className="kv"><dt>Pre-deploy</dt><dd>{gapSummary(rep.gaps?.preDeploy)}</dd><dt>Post-deploy</dt><dd>{gapSummary(rep.gaps?.postDeploy)}</dd></dl>
        {rep.disclaimer && <p className="hint">{rep.disclaimer}</p>}</section>
      <div className="row"><button type="button" className="btn btn-primary" onClick={onDownload}>Deployment report (JSON)</button></div>
    </div>
  );
}
