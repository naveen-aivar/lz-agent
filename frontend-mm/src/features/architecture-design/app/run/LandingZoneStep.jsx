import { useState } from "react";
import { Building2, CircleHelp, Flag, Layers, Network, PencilLine } from "lucide-react";
import { INFO } from "../info.js";
import { ACTIVE, lzLabel, lzVersions, newestLz, num, plural, runName, STATUS, when, sentence } from "../format.js";
import { DiagramImage, DownloadMenu, useFile } from "../components/files.jsx";
import Markdown from "../components/Markdown.jsx";
import { ModelCalls, StatusBadge, Waiting } from "../components/bits.jsx";
import LandingScene from "@/features/architecture-design/landing-scene.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Card } from "../components/ui/Card.jsx";
import { KpiTile } from "../components/ui/KpiTile.jsx";
import { Notice } from "../components/ui/Notice.jsx";
import SearchableSelect from "../components/ui/SearchableSelect.jsx";
import { Skeleton } from "../components/ui/Skeleton.jsx";
import { Tab, TabList, TabPanel, Tabs } from "../components/ui/Tabs.jsx";

const FILES = [["lz_diagram.png", "Account map (PNG)"], ["lz_diagram.svg", "Account map (SVG)"],
  ["lz_diagram.p2.png", "OU tree (PNG)"], ["lz_diagram.drawio", "draw.io (2 pages)"], ["landing_zone.md", "LZ spec (.md)"],
  ["lz_design.json", "lz_design.json"], ["platform_contract_prod.json", "platform_contract_prod.json"]];

// The landing zone (gate 1): its versions, the diagram (account map and OU tree), the spec and the model calls, and
// Revise. Approving it is the page's forward button. `pick` is the landing zone on screen (null: the newest).
export default function LandingZoneStep({ cur, pick, setPick, onRevise }) {
  const { run } = cur;
  const list = lzVersions(cur);
  const busy = ACTIVE.has(run.status);
  if (!list.length) return busy ? <LandingScene /> : <p className="tone-muted">This run has no landing zone of its own. The design is on the next step.</p>;
  const item = list.find((x) => x.lz === pick) || list[list.length - 1];
  const newest = newestLz(cur);
  const waitsForYou = item.status === "completed" && !item.approved_at && newest && item.lz === newest.lz;
  const c = item.counts || {};

  const toolbar = (
    <div className="toolbar step-toolbar">
      {list.length > 1 ? (
        <SearchableSelect label="Landing zone version" hideLabel value={String(item.lz)} onChange={(v) => setPick(Number(v))} searchPlaceholder="Search landing zones"
          options={list.slice().reverse().map((x) => ({ value: String(x.lz), label: lzLabel(x), description: `${STATUS[x.status] || x.status}${x.approved_at ? " · approved" : ""}` }))} />
      ) : <b>{lzLabel(item)}</b>}
      <StatusBadge status={item.status} />
      {c.tier ? <Badge tone="muted">{c.tier} tier</Badge> : null}
      {item.approved_at ? <Badge tone="success">Approved {when(item.approved_at)}</Badge> : null}
      {waitsForYou ? <Badge tone="warning">Waits for your approval</Badge> : null}
      <span className="toolbar-end">
        <DownloadMenu runId={run.run_id} files={item.files} list={FILES} query={{ lz: item.lz }} prefix={`${runName(run.title)}-lz${item.lz}`} />
        {newest ? <Button variant="secondary" size="sm" disabled={busy} onClick={() => onRevise("")}><PencilLine size={16} aria-hidden /> Revise</Button> : null}
      </span>
    </div>
  );

  if (ACTIVE.has(item.status)) return <div className="stack">{toolbar}<Waiting>Designing the landing zone: accounts, OUs, network and guardrails, then its diagram…</Waiting></div>;
  if (item.status === "failed") {
    return (
      <div className="stack">
        {toolbar}
        <Notice tone="danger" title={`Landing zone ${item.lz} did not finish.`}>
          {sentence(item.error)} {newest ? "Revise the landing zone to try again." : "Design it again with the button at the top."}
        </Notice>
      </div>
    );
  }
  return (
    <div className="stack">
      {toolbar}
      <div className="kpi-grid kpi-grid-5">
        <KpiTile index={0} icon={Layers} label="Tier" info={INFO.tier} value={c.tier || "–"} hint={plural(c.environments ?? 0, "environment")} />
        <KpiTile index={1} icon={Building2} label="Accounts" info={INFO.accounts} value={num(c.accounts)} hint={`in ${plural(c.ous ?? 0, "OU")} (groups)`} />
        <KpiTile index={2} icon={Network} label="VPCs" info={INFO.vpcs} value={num(c.vpcs)} hint="Private networks" />
        <KpiTile index={3} icon={CircleHelp} tone="warning" label="Open questions" info={INFO.openQuestions} value={num(c.openQuestions)} hint="For the customer" />
        <KpiTile index={4} icon={Flag} tone="violet" label="Flags for review" info={INFO.flags} value={num(c.flags ?? (item.flags || []).length)} hint="Tick them in Revise" />
      </div>
      <div className="split">
        <LzDiagram runId={run.run_id} item={item} />
        <LzSpec runId={run.run_id} item={item} />
      </div>
    </div>
  );
}

function LzDiagram({ runId, item }) {
  const [page, setPage] = useState("map");
  const files = item.files || {};
  const missing = files["lz_diagram.drawio"]
    ? "No picture: the draw.io export is not available here. Download the draw.io file (2 pages: account map and OU tree)."
    : `The landing-zone diagram was not drawn${item.diagram?.error ? `: ${item.diagram.error}` : "."}`;
  return (
    <Card title="Landing zone" info={INFO.landingZone} className="split-card">
      <Tabs value={page} onValueChange={setPage}>
        <TabList segmented label="Diagram page">
          <Tab value="map">Account map</Tab>
          <Tab value="tree">OU tree</Tab>
        </TabList>
        <TabPanel value="map">
          <DiagramImage runId={runId} query={{ lz: item.lz }} names={["lz_diagram.png", "lz_diagram.svg"]} files={files} alt="Landing zone account map" missing={missing} />
        </TabPanel>
        <TabPanel value="tree">
          <DiagramImage runId={runId} query={{ lz: item.lz }} names={["lz_diagram.p2.png", "lz_diagram.p2.svg"]} files={files} alt="Landing zone OU tree" missing={missing} />
        </TabPanel>
      </Tabs>
    </Card>
  );
}

function LzSpec({ runId, item }) {
  const [tab, setTab] = useState("spec");
  const spec = useFile(runId, { lz: item.lz }, "landing_zone.md");
  const calls = item.attempts || [];
  return (
    <Card className="split-card">
      <Tabs value={tab} onValueChange={setTab}>
        <TabList segmented label="Landing zone details">
          <Tab value="spec">Spec</Tab>
          <Tab value="calls">Model calls<span className="tab-count">{calls.length}</span></Tab>
        </TabList>
        <TabPanel value="spec">
          <div className="scroll-box" tabIndex={0} role="region" aria-label="Landing-zone spec">
            {spec.error ? <Notice tone="danger" title="We could not load landing_zone.md.">{spec.error}</Notice>
              : spec.data ? <Markdown text={spec.data.data} label="Landing-zone spec" /> : <Skeleton className="doc-skel" />}
          </div>
        </TabPanel>
        <TabPanel value="calls">
          <div className="scroll-box" tabIndex={0} role="region" aria-label="Model calls"><ModelCalls attempts={calls} /></div>
        </TabPanel>
      </Tabs>
    </Card>
  );
}
