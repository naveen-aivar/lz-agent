import { useEffect, useState } from "react";
import type { Theme } from "../theme";
const cache = new Map<string, string>();
const LEGEND: [string, string, string][] = [
  ["var(--blue-bg)", "var(--blue)", "Created by the stacks"],
  ["var(--violet-bg)", "var(--violet)", "Security OU and shared accounts, set up by Control Tower"],
  ["var(--card)", "var(--dim)", "Already exists"],
];
/** Draws the organization from the Mermaid source. mermaid loads on first use; a failure names the reason and shows the source. */
export function OrgDiagram({ source, theme }: { source: string; theme: Theme }) {
  const [svg, setSvg] = useState<string | null>(cache.get(`${theme}:${source}`) ?? null);
  const [error, setError] = useState("");
  const [full, setFull] = useState(false);
  useEffect(() => {
    const key = `${theme}:${source}`;
    const hit = cache.get(key);
    if (hit) { setSvg(hit); return; }
    let live = true;
    setSvg(null); setError("");
    (async () => {
      const { default: mermaid } = await import("mermaid");
      const dark = theme === "dark";
      mermaid.initialize({
        startOnLoad: false, securityLevel: "strict", theme: "base",
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        themeVariables: dark
          ? { background: "transparent", lineColor: "#8b94a3", primaryColor: "#0e1e33", primaryTextColor: "#e6e9ef", primaryBorderColor: "#2b8ef0", textColor: "#e6e9ef", fontSize: "14px" }
          : { background: "transparent", lineColor: "#545e70", primaryColor: "#e8f1fc", primaryTextColor: "#1a2030", primaryBorderColor: "#1b6fc4", textColor: "#1a2030", fontSize: "14px" },
        flowchart: { curve: "basis", padding: 14, htmlLabels: true },
      });
      const out = await mermaid.render(`orgsvg${Date.now()}`, source);
      cache.set(key, out.svg);
      if (live) setSvg(out.svg);
    })().catch((e: unknown) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [source, theme]);
  return (
    <div>
      <div className="legendrow">
        <div className="legend">{LEGEND.map(([bg, bd, t]) => <span key={t}><i style={{ background: bg, borderColor: bd }} />{t}</span>)}</div>
        <button type="button" className="btn btn-sm" onClick={() => setFull(true)} disabled={!svg}>View full screen</button>
      </div>
      <div className="paper">
        {svg ? <div dangerouslySetInnerHTML={{ __html: svg }} /> : error
          ? <div className="paper-empty" role="alert">The diagram could not be drawn: {error}. Its source is below.</div>
          : <div className="paper-empty">Drawing the organization…</div>}
      </div>
      <details style={{ marginTop: 12 }}><summary>Diagram source</summary><pre><code>{source}</code></pre></details>
      {full && svg && (
        <div className="overlay" role="dialog" aria-modal="true" aria-label="Organization diagram">
          <button type="button" className="btn btn-sm overlay-close" onClick={() => setFull(false)}>Close</button>
          <div className="overlay-body" dangerouslySetInnerHTML={{ __html: svg }} />
        </div>
      )}
    </div>
  );
}
