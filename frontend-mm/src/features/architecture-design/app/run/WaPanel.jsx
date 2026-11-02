import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { sampleRun } from "../sampleRun.js";
import { INFO } from "../info.js";
import { ACTIVE, num, runName, sentence } from "../format.js";
import { showToast } from "../toast.jsx";
import { DownloadMenu, useFile } from "../components/files.jsx";
import { Waiting } from "../components/bits.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Card } from "../components/ui/Card.jsx";
import { EmptyState } from "../components/ui/EmptyState.jsx";
import { Field } from "../components/ui/Field.jsx";
import { Notice } from "../components/ui/Notice.jsx";
import { Skeleton } from "../components/ui/Skeleton.jsx";
import { Tab, TabList, TabPanel, Tabs } from "../components/ui/Tabs.jsx";

// The Well-Architected review of a design version (ported from deployment/ui/wa.js): the pillar chart, the open
// findings with a decision each (apply in a new version, accept the risk, or later), and the platform findings, which
// only a landing-zone revision can fix ("Revise the landing zone" prefills that revision).
const RISK_RANK = { High: 0, Medium: 1, Low: 2 };
const DECISIONS = [["apply", "Apply"], ["risk", "Accept risk"], ["later", "Later"]];
const RISK_TONE = { High: "danger", Medium: "warning", Low: "muted" };
const signed = (n) => (typeof n !== "number" ? "" : n > 0 ? `+${n}` : String(n));
const isPlatform = (f) => f.scope === "platform";

// Horizontal bars per pillar: this version's open findings by risk, plus constraints; the previous version's findings
// as a thin bar underneath, and the change on the right.
function WaChart({ chart }) {
  const pillars = chart.pillars || [];
  const prev = new Map(((chart.previous || {}).pillars || []).map((p) => [p.pillar, p]));
  const delta = new Map((chart.delta || []).map((d) => [d.pillar, d]));
  const issues = (p) => (p.high || 0) + (p.medium || 0) + (p.low || 0);
  const max = Math.max(1, ...pillars.map((p) => issues(p) + (p.constraint || 0)), ...[...prev.values()].map(issues));
  const W = 660, LABEL = 178, BAR = 300, ROW = 46, TOP = 6;   // 182 px on the right for the change label
  return (
    <svg viewBox={`0 0 ${W} ${TOP + ROW * pillars.length}`} className="wa-chart" role="img"
      aria-label={`Open findings per pillar for version ${chart.version ?? ""}${chart.previous ? `, compared with version ${chart.previous.version}` : ""}`}>
      {pillars.map((p, i) => {
        const y = TOP + i * ROW;
        let x = LABEL;
        const bars = [];
        for (const [key, cls] of [["low", "wa-low"], ["medium", "wa-medium"], ["high", "wa-high"], ["constraint", "wa-constraint"]]) {
          const n = p[key] || 0;
          if (!n) continue;
          const w = (n / max) * BAR;
          bars.push(<rect key={key} x={x} y={y + 3} width={Math.max(w, 2)} height={16} rx={3} className={cls}><title>{`${n} ${key === "constraint" ? "constraint" : `${key} risk`}`}</title></rect>);
          if (w >= 16) bars.push(<text key={`${key}-n`} x={x + w / 2} y={y + 15} className="wa-in" textAnchor="middle">{n}</text>);
          x += w;
        }
        const q = prev.get(p.pillar);
        const d = delta.get(p.pillar) || {};
        const change = (d.high || 0) + (d.medium || 0);
        const txt = [change ? `${signed(change)} high/med` : "no change", typeof d.score_pct === "number" && d.score_pct ? `${signed(d.score_pct)}%` : ""].filter(Boolean).join(" · ");
        return (
          <g key={p.pillar}>
            <text x={0} y={y + 14} className="wa-label">{p.pillar}</text>
            <text x={0} y={y + 30} className="wa-sub">{`Score ${typeof p.score_pct === "number" ? `${p.score_pct}%` : "n/a"}`}</text>
            {bars}
            {x === LABEL ? <text x={LABEL} y={y + 15} className="wa-sub">No open findings</text> : null}
            {q && issues(q) > 0 ? <rect x={LABEL} y={y + 24} width={(issues(q) / max) * BAR} height={8} rx={2} className="wa-prev" /> : null}
            {q ? <text x={W} y={y + 15} textAnchor="end" className={change < 0 ? "wa-better" : change > 0 ? "wa-worse" : "wa-sub"}>{txt}</text> : null}
          </g>
        );
      })}
    </svg>
  );
}

function Legend({ chart }) {
  const item = (cls, text) => <span key={cls}><i className={`sw ${cls}`} />{text}</span>;
  return (
    <div className="wa-legend">
      {item("wa-high", "High risk")}{item("wa-medium", "Medium risk")}{item("wa-low", "Low risk")}{item("wa-constraint", "Project constraint")}
      {chart.previous ? item("wa-prev", `Version ${chart.previous.version}`) : null}
    </div>
  );
}

function Finding({ f, decision, onDecide, onLandingZone }) {
  const risk = f.issue_risk || f.risk;
  return (
    <li className={`finding${isPlatform(f) ? " is-platform" : ""}`}>
      <div className="finding-head">
        <code>{f.bp_id}</code><b>{f.title || ""}</b>
        {risk ? <Badge tone={RISK_TONE[risk] || "muted"}>{risk} risk</Badge> : null}
        {isPlatform(f) ? <Badge tone="info">Landing zone</Badge> : null}
        {f.status ? <span className="tone-muted">{f.status.replace(/_/g, " ")}</span> : null}
      </div>
      {f.finding ? <p>{f.finding}</p> : null}
      {f.recommendation ? <p className="finding-rec"><b>Recommendation: </b>{f.recommendation}</p> : null}
      {(f.evidence_ids || []).length ? <p className="kv">{f.evidence_ids.map((e) => <span key={e} className="mono">{e}</span>)}</p> : null}
      {f.constraint ? <p className="tone-muted">{f.constraint}</p> : null}
      {onDecide ? (
        <div className="seg" role="radiogroup" aria-label={`Decision for ${f.bp_id}`}>
          {DECISIONS.map(([val, label]) => (
            <label key={val} className={`seg-opt${decision === val ? " is-on" : ""}`}>
              <input type="radio" name={`wa-${f.bp_id}`} value={val} checked={decision === val} onChange={() => onDecide(f.bp_id, val)} />{label}
            </label>
          ))}
        </div>
      ) : null}
      {onLandingZone ? <div><Button variant="secondary" size="sm" onClick={() => onLandingZone(f)}>Revise the landing zone</Button></div> : null}
    </li>
  );
}

export default function WaPanel({ runId, cur, v, onReviseLandingZone, onNewVersion }) {
  const r = v.review || {};
  const ready = r.status && r.status !== "failed";
  const reviewFile = useFile(runId, { version: v.version }, ready ? "wa_review.json" : null);
  const chartFile = useFile(runId, { version: v.version }, ready ? "wa_chart.json" : null);
  const parsed = useMemo(() => {
    try { return reviewFile.data && chartFile.data ? { review: JSON.parse(reviewFile.data.data), chart: JSON.parse(chartFile.data.data) } : null; } catch (e) { return { error: e.message }; }
  }, [reviewFile.data, chartFile.data]);
  const review = parsed?.review;
  const all = useMemo(() => (review?.findings || []).slice().sort((a, b) => RISK_RANK[a.issue_risk] - RISK_RANK[b.issue_risk] || a.bp_id.localeCompare(b.bp_id)), [review]);
  const open = all.filter((f) => !isPlatform(f));       // the revise picker: workload findings only
  const platform = all.filter(isPlatform);

  const [decisions, setDecisions] = useState({});      // bp_id -> apply | risk | later, for the version on screen
  useEffect(() => {
    if (!review) return undefined;
    let live = true;
    const base = Object.fromEntries(open.map((f) => [f.bp_id, f.issue_risk === "Low" ? "later" : "apply"]));
    setDecisions(base);
    if (cur.run.run_id === sampleRun.id) {
      sampleRun.suggested(v.version).then((preset) => {
        if (live && preset) setDecisions(Object.fromEntries(open.map((f) => [f.bp_id, preset[f.bp_id] || "later"])));
      });
    }
    return () => { live = false; };
  }, [review, v.version]); // eslint-disable-line react-hooks/exhaustive-deps

  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [tab, setTab] = useState("open");

  if (!r.status) return <Waiting>Reviewing the design against the Well-Architected Framework…</Waiting>;
  if (r.status === "failed") return <Notice tone="danger" title="The Well-Architected review failed.">{sentence(r.error)} The decision record is still available. Create a new version to review again.</Notice>;
  const loadErr = reviewFile.error || chartFile.error || parsed?.error;
  if (loadErr) return <Notice tone="danger" title="We could not load the review.">{loadErr}</Notice>;
  if (!review) return <div className="split"><Card title="Pillars"><Skeleton className="chart-skel" /></Card><Card title="Apply in a new version"><Skeleton className="chart-skel" /></Card></div>;

  const chart = parsed.chart;
  const latest = v.version === cur.run.latest_complete_version && !ACTIVE.has(cur.run.status) && !v.stale_lz;
  const picked = (val) => open.filter((f) => decisions[f.bp_id] === val).map((f) => f.bp_id);
  const nApply = picked("apply").length, nRisk = picked("risk").length;
  const t = review.counts || {};
  const apply = async () => {
    const accepted = picked("apply"), rejected = picked("risk");
    const text = instruction.trim();
    if (!accepted.length && text.length < 5) { setErr("Select findings to apply or say what to change."); return; }
    setBusy(true); setErr(null);
    try {
      const res = await api.revise(cur.run.run_id, { instruction: text, accepted_findings: accepted, rejected_findings: rejected });
      showToast({ title: `Version ${res.version} started.`, description: "The design is revised, then reviewed again." });
      setInstruction("");
      onNewVersion();
    } catch (e) {
      setErr(`Not started: ${e.message}`);
      showToast({ title: "Not started.", description: e.message, variant: "danger" });
    } finally { setBusy(false); }
  };
  const decide = (id, val) => setDecisions((d) => ({ ...d, [id]: val }));
  const byPillar = (review.pillars || []).map((p) => [p.pillar, open.filter((f) => f.pillar === p.pillar)]).filter(([, fs]) => fs.length);
  const resolved = review.resolved_since_previous || [];
  const accepted = review.accepted_risks || [];
  const more = [
    ["Project constraints", (review.constraints || []).map((f) => <Finding key={f.bp_id} f={f} />)],
    ["Not assessed at design stage (team and process practices)", ((review.process || {}).questions || []).map((q) => <li key={q.title}>{q.title}</li>)],
    ["Assessed at the landing-zone stage (accounts and organization controls)", ((review.landing_zone || {}).best_practices || []).map((b) => <li key={b.bp_id}><code>{b.bp_id}</code> {b.title} · {b.pillar} · {b.risk}</li>)],
    ["Review warnings", (review.warnings || []).map((w) => <li key={w}>{w}</li>)],
  ].filter(([, items]) => items.length);

  return (
    <div className="stack">
      <div className="split">
        <Card title="Pillars" info={INFO.wa} className="split-card"
          description={`${review.catalog?.stamp || ""} · review round ${review.round || 1}${chart.previous ? ` · compared with version ${chart.previous.version}` : ""} · ${num(t.findings)} open findings${platform.length ? ` (${platform.length} for the landing zone)` : ""}`}
          aside={<DownloadMenu runId={runId} files={v.files} list={[["wa_review.md", "Review (.md)"], ["wa_review.json", "wa_review.json"], ["wa_chart.json", "wa_chart.json"]]} query={{ version: v.version }} prefix={`${runName(v.title)}-v${v.version}`} />}>
          <div className="wa-chart-wrap"><div className="wa-chart-scroll" tabIndex={0} role="region" aria-label="Findings per pillar"><WaChart chart={chart} /></div><Legend chart={chart} /></div>
          {(review.pillars || []).some((p) => p.summary) ? (
            <details className="fold"><summary>Pillar summaries</summary>
              <ul className="plain-list">{review.pillars.filter((p) => p.summary).map((p) => <li key={p.pillar}><b>{p.pillar}: </b>{p.summary}</li>)}</ul>
            </details>
          ) : null}
        </Card>
        <Card title="Apply in a new version" className="split-card" description="Choose a decision for each open finding below, then start a new version.">
          <div className="stack-sm">
            <p className="apply-summary"><b>{nApply}</b> to apply · <b>{nRisk}</b> accepted as risk · <b>{open.length - nApply - nRisk}</b> for later</p>
            <Field id="wa-instruction" label="Instruction" optional hint="Anything else to change, or how to apply the findings.">
              <textarea id="wa-instruction" className="textarea" rows={4} maxLength={4000} value={instruction} onChange={(e) => setInstruction(e.target.value)} />
            </Field>
            {err ? <Notice tone="danger">{err}</Notice> : null}
            {!latest ? <p className="field-hint">{v.stale_lz ? "This version follows an older landing zone: re-align it first." : "Open the latest finished version to apply its findings."}</p> : null}
            <div><Button variant="secondary" loading={busy} disabled={!latest || !open.length} onClick={apply}>{nApply ? `Apply ${nApply} finding${nApply > 1 ? "s" : ""} (new version)` : "Create new version"}</Button></div>
          </div>
        </Card>
      </div>
      <Card title="Findings" flush>
        <Tabs value={tab} onValueChange={setTab}>
          <div className="card-tabs">
            <TabList segmented label="Findings">
              <Tab value="open">Open<span className="tab-count">{open.length}</span></Tab>
              {platform.length ? <Tab value="platform">Landing zone<span className="tab-count">{platform.length}</span></Tab> : null}
              {resolved.length ? <Tab value="resolved">Resolved<span className="tab-count">{resolved.length}</span></Tab> : null}
              {accepted.length ? <Tab value="accepted">Accepted<span className="tab-count">{accepted.length}</span></Tab> : null}
              {more.length ? <Tab value="more">More</Tab> : null}
            </TabList>
          </div>
          <TabPanel value="open" className="card-tab-panel">
            {byPillar.length ? byPillar.map(([pillar, fs]) => (
              <section key={pillar} className="gap-group">
                <h3 className="sub-title">{pillar}<span className="tab-count">{fs.length}</span></h3>
                <ul className="findings fade-list">{fs.map((f) => <Finding key={f.bp_id} f={f} decision={decisions[f.bp_id]} onDecide={decide} />)}</ul>
              </section>
            )) : <EmptyState title="No open findings for the workload." />}
          </TabPanel>
          <TabPanel value="platform" className="card-tab-panel">
            <p className="field-hint">Only a landing-zone revision can fix these (accounts, organization controls, central network or security services). They are not applied to the design.</p>
            <ul className="findings fade-list">{platform.map((f) => <Finding key={f.bp_id} f={f} onLandingZone={(x) => onReviseLandingZone(`${x.bp_id} ${x.title || ""}: ${x.recommendation || x.finding || ""}`.trim())} />)}</ul>
          </TabPanel>
          <TabPanel value="resolved" className="card-tab-panel">
            <ul className="findings fade-list">{resolved.map((x) => <li key={x.bp_id} className="finding is-ok"><div className="finding-head"><code>{x.bp_id}</code><b>{x.title || ""}</b></div><p>{x.how}</p></li>)}</ul>
          </TabPanel>
          <TabPanel value="accepted" className="card-tab-panel">
            <ul className="findings fade-list">{accepted.map((f) => <Finding key={f.bp_id} f={f} />)}</ul>
          </TabPanel>
          <TabPanel value="more" className="card-tab-panel">
            <div className="stack">
              {more.map(([title, items]) => (
                <section key={title} className="gap-group">
                  <h3 className="sub-title">{title}<span className="tab-count">{items.length}</span></h3>
                  <ul className="findings plain-list fade-list">{items}</ul>
                </section>
              ))}
            </div>
          </TabPanel>
        </Tabs>
      </Card>
    </div>
  );
}
