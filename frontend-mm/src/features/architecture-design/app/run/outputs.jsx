import { useEffect, useState } from "react";
import { api } from "../api.js";
import { INFO } from "../info.js";
import { humanKey, IAC_NAME, iacItems, num, runName, sentence } from "../format.js";
import { DiagramImage, DownloadMenu, useFile } from "../components/files.jsx";
import Markdown from "../components/Markdown.jsx";
import { Waiting } from "../components/bits.jsx";
import { Card } from "../components/ui/Card.jsx";
import { EmptyState } from "../components/ui/EmptyState.jsx";
import { Notice } from "../components/ui/Notice.jsx";
import { Skeleton } from "../components/ui/Skeleton.jsx";

// The outputs of one design version (tabs Diagram, Decision record, Usage, Gaps), ported from deployment/ui/outputs.js.
const CHECK_TEXT = { pass: "passed", pass_with_warnings: "passed with warnings (see Gaps)", fail: "failed" };
const prefixOf = (v) => `${runName(v.title)}-v${v.version}`;

export function DiagramTab({ runId, v }) {
  const d = v.diagram || {};
  const files = v.files || {};
  const images = ["architecture.png", "architecture.svg", "diagram.png", "diagram.svg"];
  if (!d.status) return <Waiting>Drawing the diagram…</Waiting>;
  if (d.status === "failed" && !images.some((n) => files[n])) {
    return <Notice tone="danger" title="The diagram could not be drawn.">{sentence(d.error)} The decision record is still available. Revise the design or start again.</Notice>;
  }
  const s = d.summary || {};
  const downloads = [["architecture.png", "PNG"], ["architecture.svg", "SVG"], ["architecture.drawio", "draw.io"], ["diagram.png", "PNG"], ["diagram.svg", "SVG"], ["diagram.drawio", "draw.io"]];
  return (
    <Card title="Architecture diagram" info={INFO.diagram}
      description={`${num(s.components)} components, ${num(s.relationships)} relationships, ${num(s.boundaries)} groups · layout check ${CHECK_TEXT[d.report_status] || d.report_status || "–"} · ${d.model_calls ? `${d.model_calls} model calls` : "drawn from the design, no model call"}${v.lz_version ? ` · with landing zone ${v.lz_version}'s network hub` : ""}`}
      aside={<DownloadMenu runId={runId} files={files} list={downloads} query={{ version: v.version }} prefix={prefixOf(v)} />}>
      <DiagramImage runId={runId} query={{ version: v.version }} names={images} files={files} alt={`AWS architecture diagram: ${v.title || "architecture"}`}
        missing="No picture: the draw.io export is not available here. Download the draw.io file and open it in draw.io." />
    </Card>
  );
}

export function AdrTab({ runId, v }) {
  const adr = useFile(runId, { version: v.version }, "adr.md");
  return (
    <Card title="Decision record" info={INFO.decisions}
      aside={<DownloadMenu runId={runId} files={v.files} list={[["adr.md", "ADR (.md)"], ["spec.json", "spec.json"], ["summary.json", "summary.json"], ["design.json", "design.json"]]} query={{ version: v.version }} prefix={prefixOf(v)} />}>
      {adr.error ? <Notice tone="danger" title="We could not load the decision record.">{adr.error}</Notice>
        : adr.data ? <Markdown text={adr.data.data} label="Decision record" className="md-doc" /> : <Skeleton className="doc-skel" />}
    </Card>
  );
}

function KeyValues({ item }) {
  return (
    <span className="kv">
      {Object.entries(item).filter(([k]) => k !== "service").map(([k, val]) => (
        <span key={k}><b>{humanKey(k)}</b> {typeof val === "object" && val !== null ? JSON.stringify(val) : num(val)}</span>
      ))}
    </span>
  );
}

export function UsageTab({ runId, v }) {
  const u = v.usage || {};
  const usage = useFile(runId, { version: v.version }, u.status && u.status !== "failed" ? "usage.json" : null);
  const notes = useFile(runId, { version: v.version }, u.status && u.status !== "failed" && v.files?.["usage_assumptions.md"] ? "usage_assumptions.md" : null);
  if (!u.status) return <Waiting>Estimating usage…</Waiting>;
  if (u.status === "failed") return <Notice tone="danger" title="The usage estimate failed.">{sentence(u.error)} Create a new version to try again.</Notice>;
  let parsed = null;
  try { parsed = usage.data ? JSON.parse(usage.data.data) : null; } catch { parsed = null; }
  const groups = parsed && typeof parsed.services === "object" && parsed.services ? Object.entries(parsed.services).filter(([, items]) => Array.isArray(items) && items.length) : [];
  return (
    <Card title="Usage estimate" info={INFO.usage} description="Monthly usage per service, for the cost calculator."
      aside={<DownloadMenu runId={runId} files={v.files} list={[["usage.json", "usage.json"]]} query={{ version: v.version }} prefix={prefixOf(v)} />}>
      {usage.error ? <Notice tone="danger" title="We could not load the usage estimate.">{usage.error}</Notice>
        : !usage.data ? <Skeleton className="doc-skel" />
          : groups.length ? (
            <div className="stack">
              {groups.map(([cat, items]) => (
                <section key={cat} className="usage-group">
                  <h3 className="sub-title">{humanKey(cat).replace(/^./, (ch) => ch.toUpperCase())}</h3>
                  <div className="tbl-wrap">
                    <table className="tbl tbl-plain">
                      <thead><tr><th scope="col">Service</th><th scope="col">Configuration and monthly usage</th></tr></thead>
                      <tbody className="fade-list">
                        {items.map((it, i) => <tr key={`${it.service}-${i}`}><td data-label="Service"><b>{it.service || "–"}</b></td><td data-label="Usage"><KeyValues item={it} /></td></tr>)}
                      </tbody>
                    </table>
                  </div>
                </section>
              ))}
              {notes.data?.data?.trim() ? (
                <details className="fold" open><summary>Usage assumptions</summary><Markdown text={notes.data.data} label="Usage assumptions" /></details>
              ) : null}
            </div>
          ) : <pre className="raw">{JSON.stringify(parsed ?? usage.data.data, null, 2)}</pre>}
    </Card>
  );
}

// One group of gaps: a heading with its count and the items (tone: red for questions, blue for additions).
function GapGroup({ title, items, tone = "" }) {
  if (!items.length) return null;
  return (
    <section className="gap-group">
      <h3 className="sub-title">{title}<span className="tab-count">{items.length}</span></h3>
      <ul className={`gap-list fade-list${tone ? ` gap-${tone}` : ""}`}>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </section>
  );
}
const asText = (q) => (typeof q === "string" ? q : q.text || q.message || JSON.stringify(q));

export function GapsTab({ runId, v, cur }) {
  const design = useFile(runId, { version: v.version }, "design.json");
  const [iacFlagged, setIacFlagged] = useState(null);   // { title, items } from the newest finished IaC's scope.json
  const doneIac = iacItems(cur, v).filter((x) => x.status === "completed").pop();
  useEffect(() => {
    let live = true;
    setIacFlagged(null);
    if (!doneIac || !(doneIac.counts || {}).flagged) return undefined;
    api.file(runId, { version: v.version, iac: doneIac.iac }, "scope.json").then((f) => {
      const scope = JSON.parse(f.data);
      if (live) setIacFlagged({ title: `${IAC_NAME} ${doneIac.iac}: flagged for manual review`, items: scope.flagged || [] });
    }).catch(() => {});   // the IaC step still shows SCOPE.md
    return () => { live = false; };
  }, [runId, v.version, doneIac?.iac]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!design.data && !design.error) return <Card title="Gaps and assumptions" info={INFO.gaps}><Skeleton className="doc-skel" /></Card>;
  let d = null;
  try { d = design.data ? JSON.parse(design.data.data) : null; } catch { d = null; }
  const diag = v.diagram || {};
  const groups = [
    d ? <GapGroup key="q" title="Open questions for the customer" tone="red" items={(d.open_questions || []).map(asText)} /> : null,
    d ? <GapGroup key="a" title="Assumptions in the design" items={(d.assumptions || []).map((a) => <><b>{a.id || ""} </b>{a.text || ""}{a.reason ? <span className="cell-sub">{a.reason}</span> : null}</>)} /> : null,
    d ? <GapGroup key="c" title="Components the requirements did not state" tone="blue" items={(d.components || []).filter((c) => c.assumed).map((c) => <><b>{c.name} </b><span className="tone-muted">{c.service || ""}</span>{c.assumption_reason ? <span className="cell-sub">{c.assumption_reason}</span> : null}</>)} /> : null,
    <GapGroup key="u" title="Diagram: items needing confirmation" tone="red" items={(diag.unresolved || []).map((u) => <><b>{u.about} </b>{u.suggestion || ""}{u.reasoning ? <span className="cell-sub">{u.reasoning}</span> : null}</>)} />,
    <GapGroup key="x" title="Diagram: contradictions in the input" tone="red" items={((diag.contradictions || {}).contradictions || []).map((c) => <><b>{c.subject}: </b>{c.claim_a?.statement || ""} vs {c.claim_b?.statement || ""}{c.note ? <span className="cell-sub">{c.note}</span> : null}</>)} />,
    iacFlagged ? <GapGroup key="i" title={iacFlagged.title} tone="red" items={iacFlagged.items.map((f) => <><b>{f.item}: </b>{f.issue || ""}<span className="cell-sub">{f.action || "left as is"}</span></>)} /> : null,
    <GapGroup key="s" title="Diagram suggestions and warnings" tone="blue" items={[...(diag.suggestions || []), ...(diag.warnings || [])].map(asText)} />,
  ];
  const any = (d && ((d.open_questions || []).length || (d.assumptions || []).length || (d.components || []).some((c) => c.assumed)))
    || (diag.unresolved || []).length || ((diag.contradictions || {}).contradictions || []).length || iacFlagged?.items.length
    || (diag.suggestions || []).length || (diag.warnings || []).length;
  return (
    <Card title="Gaps and assumptions" info={INFO.gaps}>
      {any ? <div className="stack">{groups}</div>
        : <EmptyState title={d ? "No gaps or assumptions were flagged." : "The design file could not be loaded."} description={design.error || undefined} />}
    </Card>
  );
}
