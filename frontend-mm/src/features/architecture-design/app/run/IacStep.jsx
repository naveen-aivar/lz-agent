import { useMemo, useState } from "react";
import { Building2, FileCheck2, Flag, ShieldCheck, SlidersHorizontal, PencilLine } from "lucide-react";
import { INFO } from "../info.js";
import { ACTIVE, IAC_NAME, iacItems, iacLabel, isDone, num, plural, runName, STATUS, when, words, sentence } from "../format.js";
import { DownloadMenu, useFile } from "../components/files.jsx";
import Markdown from "../components/Markdown.jsx";
import { ModelCalls, StatusBadge, Waiting } from "../components/bits.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Card } from "../components/ui/Card.jsx";
import { EmptyState } from "../components/ui/EmptyState.jsx";
import { KpiTile } from "../components/ui/KpiTile.jsx";
import { Notice } from "../components/ui/Notice.jsx";
import SearchableSelect from "../components/ui/SearchableSelect.jsx";
import { Skeleton } from "../components/ui/Skeleton.jsx";
import { Tab, TabList, TabPanel, Tabs } from "../components/ui/Tabs.jsx";

const FILES = [["terraform.zip", "Terraform (.zip)"], ["cloudformation.zip", "CloudFormation (.zip)"],
  ["scope.json", "scope.json"], ["SCOPE.md", "SCOPE.md"], ["iac_validation.json", "iac_validation.json"]];

// The IaC flags (scope.json "flagged") in the shape of the revise dialog's flags: ticking one adds an instruction.
export const iacFlags = (scope) => ((scope && scope.flagged) || []).map((f) => ({ severity: "warning", area: f.item || "scope",
  message: `${f.item}: ${f.issue}${f.action ? ` (${f.action})` : ""}`, suggested_instruction: `Fix the flagged item ${f.item}: ${f.issue}` }));

// The Landing Zone - IaC (after gate 2), for the design version on screen: Terraform and CloudFormation for the approved
// landing zone, its organization, its scope and the model calls. Generating and approving it is the page's forward
// button; revising custom SCPs is a dialog.
export default function IacStep({ cur, v, pick, setPick, onRevise, onOpenLandingZone }) {
  const { run } = cur;
  const list = iacItems(cur, v);
  const busy = ACTIVE.has(run.status);
  if (!isDone(v)) return <EmptyState title={`Approve a design version to generate its ${IAC_NAME}.`} description="Terraform and CloudFormation for the approved landing zone." />;
  if (!v.approved_at) {
    return <EmptyState title={v.stale_lz ? "This version follows an older landing zone." : `Approve version ${v.version} to generate its ${IAC_NAME}.`}
      description={v.stale_lz ? "Re-align the design, then approve the new version." : `It is made from landing zone ${v.lz_version || ""}.`} />;
  }
  if (!list.length) {
    return <EmptyState title={busy ? `The run is working; the ${IAC_NAME} can start when it finishes.` : `This version has no ${IAC_NAME} yet.`}
      description={busy ? undefined : "Generate it with the button at the top."} />;
  }
  const item = list.find((x) => x.iac === pick) || list[list.length - 1];
  const latestDone = list.filter((x) => x.status === "completed").pop();
  return <IacBody cur={cur} v={v} list={list} item={item} latestDone={latestDone} busy={busy} setPick={setPick} onRevise={onRevise} onOpenLandingZone={onOpenLandingZone} />;
}

function IacBody({ cur, v, list, item, latestDone, busy, setPick, onRevise, onOpenLandingZone }) {
  const runId = cur.run.run_id;
  const q = { version: v.version, iac: item.iac };
  const done = item.status === "completed";
  const scopeFile = useFile(runId, q, done ? "scope.json" : null);
  const scope = useMemo(() => { try { return scopeFile.data ? JSON.parse(scopeFile.data.data) : null; } catch { return null; } }, [scopeFile.data]);
  const c = item.counts || {};
  const val = item.validation || {};

  const toolbar = (
    <div className="toolbar step-toolbar">
      {list.length > 1 ? (
        <SearchableSelect label={IAC_NAME} hideLabel value={String(item.iac)} onChange={(x) => setPick(Number(x))} searchPlaceholder="Search IaC versions"
          options={list.slice().reverse().map((x) => ({ value: String(x.iac), label: iacLabel(x), description: `${STATUS[x.status] || x.status}${x.approved_at ? " · approved" : ""}` }))} />
      ) : <b>{iacLabel(item)}</b>}
      <StatusBadge status={item.status} />
      {item.lz_version ? <Badge tone="muted">From landing zone {item.lz_version}</Badge> : null}
      {item.approved_at ? <Badge tone="success">Approved {when(item.approved_at)}</Badge> : null}
      <span className="toolbar-end">
        <DownloadMenu runId={runId} files={item.files} list={FILES} query={q} prefix={`${runName(v.title)}-v${v.version}-iac${item.iac}`} />
        {latestDone ? <Button variant="secondary" size="sm" disabled={busy} onClick={() => onRevise(latestDone, scope)}><PencilLine size={16} aria-hidden /> Revise SCPs</Button> : null}
      </span>
    </div>
  );

  if (ACTIVE.has(item.status)) return <div className="stack">{toolbar}<Waiting>Generating the {IAC_NAME}: scope, Terraform and CloudFormation…</Waiting></div>;
  if (item.status === "failed") {
    return (
      <div className="stack">
        {toolbar}
        {item.needs_lz_revision ? (
          <Notice tone="warning" title="This change needs a landing-zone revision." action={<Button variant="secondary" size="sm" onClick={onOpenLandingZone}>Open the landing zone</Button>}>
            {String(item.error || "").replace(/^needs a landing-zone revision: /, "")}
          </Notice>
        ) : <Notice tone="danger" title={`${IAC_NAME} ${item.iac} did not finish.`}>{sentence(item.error)}</Notice>}
      </div>
    );
  }
  return (
    <div className="stack">
      {toolbar}
      <div className="kpi-grid kpi-grid-5">
        <KpiTile index={0} icon={Building2} label="Accounts" info={INFO.accounts} value={num(c.accounts)} hint={`in ${plural(c.ous, "OU")}`} />
        <KpiTile index={1} icon={ShieldCheck} label="SCPs" info={INFO.scps} value={num(c.scps)} hint={`${num(c.customScps)} custom, for review`} />
        <KpiTile index={2} icon={SlidersHorizontal} tone="violet" label="Controls" info={INFO.controls} value={num(c.controls)} hint={`${num(c.unsupported)} designed, not codified`} />
        <KpiTile index={3} icon={Flag} tone="warning" label="Flagged for review" info={INFO.flags} value={num(c.flagged || 0)} hint={plural(c.openQuestions ?? 0, "open question")} />
        <KpiTile index={4} icon={FileCheck2} tone={val.cfn_lint === "failed" ? "danger" : "success"} label="Template check" info={INFO.cfnLint}
          value={val.cfn_lint === "passed" ? "Passed" : val.cfn_lint === "failed" ? "Failed" : "Skipped"} hint={`Scope: ${words(c.scopeStatus)}`} />
      </div>
      <div className="split">
        <Card title="Organization" info={INFO.iac} className="split-card">
          <div className="scroll-box" tabIndex={0} role="region" aria-label="Organization">
            {scopeFile.error ? <Notice tone="danger" title={`We could not load the ${IAC_NAME}.`}>{scopeFile.error}</Notice>
              : scope ? <OrgTree scope={scope} /> : <Skeleton className="doc-skel" />}
          </div>
        </Card>
        <IacDetails runId={runId} q={q} attempts={item.attempts || []} />
      </div>
    </div>
  );
}

function IacDetails({ runId, q, attempts }) {
  const [tab, setTab] = useState("scope");
  const md = useFile(runId, q, "SCOPE.md");
  return (
    <Card className="split-card">
      <Tabs value={tab} onValueChange={setTab}>
        <TabList segmented label="IaC details">
          <Tab value="scope">Scope</Tab>
          <Tab value="calls">Model calls<span className="tab-count">{attempts.length}</span></Tab>
        </TabList>
        <TabPanel value="scope">
          <div className="scroll-box" tabIndex={0} role="region" aria-label="Scope">
            {md.error ? <Notice tone="danger" title="We could not load SCOPE.md.">{md.error}</Notice> : md.data ? <Markdown text={md.data.data} label="Scope" /> : <Skeleton className="doc-skel" />}
          </div>
        </TabPanel>
        <TabPanel value="calls"><div className="scroll-box" tabIndex={0} role="region" aria-label="Model calls"><ModelCalls attempts={attempts} tokens={false} /></div></TabPanel>
      </Tabs>
    </Card>
  );
}

// Root -> OUs -> child OUs -> accounts, from scope.json (ORG-STRUCTURE.md stays in the bundle for GitHub).
function OrgTree({ scope }) {
  const ous = scope.ous || [];
  const accounts = scope.accounts || [];
  const lg = scope.logging || {};
  const created = new Set((scope.missingRequired || []).map((m) => m.replace(/^email for account /, "")));
  const targets = (name, items) => (items || []).filter((x) => (x.targets || []).includes(name)).length;
  const account = (a) => (
    <li key={`a-${a.name}`} className="org-acct">
      <b>{a.name}</b>
      <span className="tone-muted"> · {a.kind}{a.kind === "management" || a.provisioning === "existing" ? " · existing" : created.has(a.name) ? " · created from an email you provide" : ""}</span>
      {(a.kind === "log-archive" && lg.logArchiveAccountId) || (a.kind === "audit" && lg.auditAccountId)
        ? <span className="tone-muted mono"> · id {a.kind === "audit" ? lg.auditAccountId : lg.logArchiveAccountId}</span> : null}
    </li>
  );
  const ouNode = (o) => {
    const kids = ous.filter((x) => x.parent === o.name);
    const accts = accounts.filter((a) => a.ou === o.name);
    const scps = targets(o.name, scope.scps), controls = targets(o.name, scope.controls);
    return (
      <li key={`o-${o.name}`} className="org-ou">
        <b>{o.name} OU</b>
        <span className="tone-muted">{[scps ? ` · SCPs: ${scps}` : "", controls ? ` · controls: ${controls}` : ""].join("")}</span>
        {kids.length || accts.length ? <ul>{kids.map(ouNode)}{accts.map(account)}</ul> : null}
      </li>
    );
  };
  const rootScps = (scope.scps || []).filter((p) => (p.targets || []).includes("root")).map((p) => p.id);
  return (
    <ul className="org-tree fade-list">
      <li className="org-root">
        <b>Root</b>{rootScps.length ? <span className="tone-muted"> · SCPs: {rootScps.join(", ")}</span> : null}
        <ul>{ous.filter((o) => !o.parent).map(ouNode)}{accounts.filter((a) => a.ou === "root").map(account)}</ul>
      </li>
    </ul>
  );
}
