import { useEffect, useState } from "react";
import { Boxes, Gauge, ListChecks, PencilLine, ScanSearch, Server } from "lucide-react";
import { INFO } from "../info.js";
import { ACTIVE, CHECK, STATUS, dur, hasOutputs, newestLz, num, plural, versionLabel, when, words, sentence } from "../format.js";
import { StatusBadge, Waiting } from "../components/bits.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { KpiTile } from "../components/ui/KpiTile.jsx";
import { Notice } from "../components/ui/Notice.jsx";
import { SkeletonText } from "../components/ui/Skeleton.jsx";
import SearchableSelect from "../components/ui/SearchableSelect.jsx";
import { Tab, TabList, TabPanel, Tabs } from "../components/ui/Tabs.jsx";
import { AdrTab, DiagramTab, GapsTab, UsageTab } from "./outputs.jsx";
import WaPanel from "./WaPanel.jsx";

export const DESIGN_TABS = ["diagram", "wa", "adr", "usage", "gaps"];

// The design (gate 2): one version at a time (the picker), its numbers in one row, and its outputs as tabs. Revising
// is a dialog (Revise the design); approving a version is the page's forward button.
export default function DesignStep({ cur, v, setPick, tab, setTab, onRevise, onRealign, onOpenLandingZone, onReviseLandingZone, onNewVersion }) {
  const { run } = cur;
  const versions = cur.versions || [];
  const busy = ACTIVE.has(run.status);
  if (!v) {
    return run.lz_approved
      ? <Waiting>The design starts in a moment.</Waiting>
      : <p className="tone-muted">The design starts after the landing zone is approved.</p>;
  }
  const canRevise = !busy && !!run.latest_complete_version && cur.awaiting !== "lz_approval";
  const latest = versions[versions.length - 1];
  const failed = latest && latest.status === "failed" && latest.error;

  const toolbar = (
    <div className="toolbar step-toolbar">
      {versions.length > 1 ? (
        <SearchableSelect label="Design version" hideLabel value={String(v.version)} onChange={(x) => setPick(Number(x))} searchPlaceholder="Search versions"
          options={versions.slice().reverse().map((x) => ({ value: String(x.version), label: versionLabel(x),
            description: [STATUS[x.status] || x.status, x.approved_at ? "approved" : "", x.stale_lz ? "older landing zone" : ""].filter(Boolean).join(" · ") }))} />
      ) : <b>{versionLabel(v)}</b>}
      <StatusBadge status={v.status} />
      {v.lz_version ? <Badge tone="muted">Landing zone {v.lz_version}</Badge> : null}
      {v.approved_at ? <Badge tone="success">Approved {when(v.approved_at)}</Badge> : null}
      <span className="toolbar-end">
        <Button variant="secondary" size="sm" disabled={!canRevise} onClick={onRevise}><PencilLine size={16} aria-hidden /> Revise the design</Button>
      </span>
    </div>
  );

  return (
    <div className="stack">
      {toolbar}
      {failed ? <Notice tone="danger" title={`Version ${latest.version} did not finish.`}>{sentence(latest.error)}</Notice> : null}
      <StaleNotice cur={cur} v={v} onRealign={onRealign} onOpenLandingZone={onOpenLandingZone} />
      {!hasOutputs(v) ? (
        v.status === "failed"
          ? <p className="tone-muted">This version has no outputs.</p>
          : <Waiting>The outputs appear here as each step finishes.</Waiting>
      ) : (
        <>
          <DesignTiles v={v} />
          <DesignTabs cur={cur} v={v} tab={tab} setTab={setTab} onReviseLandingZone={onReviseLandingZone} onNewVersion={onNewVersion} />
        </>
      )}
    </div>
  );
}

// "Version 2 was designed against landing zone 1, and the landing zone has changed since": re-align, or approve first.
function StaleNotice({ cur, v, onRealign, onOpenLandingZone }) {
  const { run } = cur;
  const newest = newestLz(cur);
  if (!v.stale_lz || !newest) return null;
  const approved = Number(run.lz_approved || 0);
  const waitingLz = newest.lz !== approved;
  return (
    <Notice tone="warning" title={`Version ${v.version} follows an older landing zone.`}
      action={!waitingLz && v.version === run.latest_complete_version
        ? <Button size="sm" disabled={ACTIVE.has(run.status)} onClick={() => onRealign(approved)}>Re-align to landing zone {approved}</Button>
        : waitingLz ? <Button variant="secondary" size="sm" onClick={onOpenLandingZone}>Open the landing zone</Button> : null}>
      It was designed against landing zone {v.lz_version || "?"}; the newest is landing zone {newest.lz}.{" "}
      {waitingLz ? `Approve landing zone ${newest.lz}, then re-align the design.` : "Re-align the design to it before approving a version."}
    </Notice>
  );
}

function DesignTiles({ v }) {
  const c = v.adr?.counts || {};
  const d = v.diagram || {};
  const r = v.review || {};
  const rc = r.counts || {};
  const services = v.usage?.counts ? v.usage.counts.entries : undefined;
  const waValue = !r.status ? <SkeletonText>00%</SkeletonText> : r.status === "failed" ? "Failed" : typeof rc.score_pct === "number" ? `${rc.score_pct}%` : "–";
  const diagramValue = d.status === "completed" ? (CHECK[d.report_status] || "Passed") : d.status === "failed" ? "Failed" : <SkeletonText>Passed</SkeletonText>;
  return (
    <div className="kpi-grid kpi-grid-5">
      <KpiTile index={0} icon={Gauge} label="Well-Architected" info={INFO.waScore} value={waValue}
        valueTone={r.status === "failed" ? "danger" : undefined} hint={r.status && r.status !== "failed" ? plural(rc.high ?? 0, "high risk") : "Score"} hintTone={rc.high ? "danger" : undefined} />
      <KpiTile index={1} icon={ListChecks} label="Decisions" info={INFO.decisions} value={num(c.decisions)} hint={`From ${plural(c.requirements, "requirement")}`} />
      <KpiTile index={2} icon={Boxes} label="Components" info={INFO.components} value={num(c.components)} hint={plural((c.assumptions || 0) + (c.assumed_components || 0), "assumption")} />
      <KpiTile index={3} icon={ScanSearch} tone={d.status === "failed" ? "danger" : "success"} label="Diagram check" info={INFO.diagramCheck} value={diagramValue}
        hint={d.report_status === "pass_with_warnings" ? "With warnings (see Gaps)" : "Layout and labels"} />
      <KpiTile index={4} icon={Server} tone="teal" label="Services estimated" info={INFO.services} value={services !== undefined ? num(services) : <SkeletonText>00</SkeletonText>}
        hint={[v.adr?.conform ? `Platform contract ${words(v.adr.conform.status)}` : null, v.seconds ? `${dur(v.seconds)} agent time` : null].filter(Boolean).join(" · ") || "Monthly usage"} />
    </div>
  );
}

function DesignTabs({ cur, v, tab, setTab, onReviseLandingZone, onNewVersion }) {
  const runId = cur.run.run_id;
  const [shown, setShown] = useState(tab);
  useEffect(() => setShown(tab), [tab]);
  const choose = (t) => { setShown(t); setTab(t); };
  return (
    <Tabs value={shown} onValueChange={choose}>
      <TabList segmented label="Outputs of the design">
        <Tab value="diagram">Diagram</Tab>
        <Tab value="wa">Well-Architected</Tab>
        <Tab value="adr">Decision record</Tab>
        <Tab value="usage">Usage</Tab>
        <Tab value="gaps">Gaps</Tab>
      </TabList>
      <TabPanel value="diagram"><DiagramTab runId={runId} v={v} /></TabPanel>
      <TabPanel value="wa"><WaPanel runId={runId} cur={cur} v={v} onReviseLandingZone={onReviseLandingZone} onNewVersion={onNewVersion} /></TabPanel>
      <TabPanel value="adr"><AdrTab runId={runId} v={v} /></TabPanel>
      <TabPanel value="usage"><UsageTab runId={runId} v={v} /></TabPanel>
      <TabPanel value="gaps"><GapsTab runId={runId} v={v} cur={cur} /></TabPanel>
    </Tabs>
  );
}
