import { useEffect, useMemo, useState } from "react";
import type { Client } from "../api/client";
import { parseScope } from "../logic/design";
import type { CustomScp, Scope } from "../logic/design";
import { buildEdits, draftError, draftOf, fillPolicy, isDirty, missingValues, parsePolicy, placeholders } from "../logic/scps";
import type { Draft } from "../logic/scps";
import { BasisBadge } from "./Basis";
import { useToast } from "./Toasts";
interface Props {
  runId: string;
  scope: Scope;
  /** The sha of `scope`: the server refuses the save if the design has changed since. */
  sha: string;
  api: Pick<Client, "editCustomScps">;
  /** Called with the saved scope so the page shows what the downloads now contain. */
  onSaved: (scope: Scope, sha: string, raw: unknown) => void;
  onNext?: () => void;
  nextLabel?: string;
}
function Card({ entry, draft, onChange }: { entry: CustomScp; draft: Draft; onChange: (d: Draft) => void }) {
  const [editing, setEditing] = useState(false);
  const names = placeholders(draft.policyText);
  const parsed = parsePolicy(draft.policyText);
  const missing = missingValues(draft);
  const info = Object.fromEntries(entry.inputs.map((i) => [i.name, i]));
  const preview = "policy" in parsed ? JSON.stringify(fillPolicy(parsed.policy, draft.values), null, 2) : null;
  const ready = "policy" in parsed && missing.length === 0;
  return (
    <div className="card scp">
      <div className="card-head">
        <div><h2>{entry.title}</h2><div className="hint">{entry.description}</div></div>
        <span className={`badge ${ready ? "badge-green" : "badge-amber"}`}>{ready ? "Ready" : names.length ? `${missing.length} value${missing.length === 1 ? "" : "s"} needed` : "Check the policy"}</span>
      </div>
      <div className="row"><span className="hint">Applies to</span>{entry.targets.map((t) => <span key={t} className="badge badge-blue">{t}</span>)}<BasisBadge basis={entry.basis} /></div>
      {entry.warnings.length > 0 && <div className="notice notice-warn" style={{ marginTop: 10 }}>{entry.warnings.join(" ")}</div>}
      {names.length > 0 && (
        <div className="fields">
          {names.map((n) => (
            <label key={n}>{n.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase())}
              <input value={draft.values[n] ?? ""} placeholder={info[n]?.example || ""} aria-label={n}
                onChange={(e) => onChange({ ...draft, values: { ...draft.values, [n]: e.target.value } })} />
              <span className="hint">{info[n]?.description ?? "Added in the editor"}</span>
            </label>
          ))}
        </div>
      )}
      {names.length === 0 && "policy" in parsed && <p className="hint">This policy has no values to fill in.</p>}
      <details open={editing} onToggle={(e) => setEditing((e.target as HTMLDetailsElement).open)} style={{ marginTop: 10 }}>
        <summary>Edit the policy JSON</summary>
        <p className="hint">Keep <code>{"{{NAME}}"}</code> where a value should be entered above. The policy must stay Deny-only and under 5120 characters.</p>
        <textarea className="code" rows={14} spellCheck={false} aria-label={`Policy JSON for ${entry.title}`} value={draft.policyText}
          onChange={(e) => onChange({ ...draft, policyText: e.target.value })} />
        {"error" in parsed && <p className="errtext" role="alert">{parsed.error}</p>}
      </details>
      {preview && <details style={{ marginTop: 8 }}><summary>Policy with your values</summary><pre><code>{preview}</code></pre></details>}
    </div>
  );
}
/** Review and edit the custom SCPs: one field per placeholder, and the policy JSON for anything else. */
export function ScpEditor({ runId, scope, sha, api, onSaved, onNext, nextLabel }: Props) {
  const toast = useToast();
  const entries = scope.customScps;
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() => Object.fromEntries(entries.map((e) => [e.id, draftOf(e)])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setDrafts(Object.fromEntries(entries.map((e) => [e.id, draftOf(e)]))); }, [entries]);
  const dirty = useMemo(() => entries.filter((e) => drafts[e.id] && isDirty(e, drafts[e.id]!)), [entries, drafts]);
  const problem = dirty.map((e) => draftError(drafts[e.id]!)).find((x) => x) ?? null;
  const unfinished = entries.filter((e) => drafts[e.id] && missingValues(drafts[e.id]!).length > 0).length;
  async function save() {
    setBusy(true);
    setError("");
    try {
      const saved = await api.editCustomScps(runId, { baseSha: sha, edits: buildEdits(entries, drafts) });
      onSaved(parseScope(saved.scope), saved.sha, saved);
      toast("Saved. The downloads now include these values.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  if (!entries.length) {
    return <div><div className="empty">This SOW needs no custom policies beyond the catalog.</div>{onNext && <div className="row"><button type="button" className="btn btn-primary" onClick={onNext}>{nextLabel ?? "Continue"}</button></div>}</div>;
  }
  return (
    <div>
      <div className="notice notice-info">
        <strong>The model wrote these policies from the SOW with sample values.</strong> Enter your real values, check each policy against the
        SOW, and test it on a non-production account first. Saving updates your downloads (<code>custom-scps/</code>). It does not apply anything to AWS.
      </div>
      {entries.map((e) => <Card key={e.id} entry={e} draft={drafts[e.id] ?? draftOf(e)} onChange={(d) => setDrafts({ ...drafts, [e.id]: d })} />)}
      {(error || problem) && <p className="errtext" role="alert">{error || problem}</p>}
      <div className="row">
        <button type="button" className="btn btn-primary" disabled={busy || dirty.length === 0 || !!problem} onClick={() => void save()}>
          {busy ? "Saving…" : dirty.length ? `Save ${dirty.length} change${dirty.length === 1 ? "" : "s"}` : "No changes to save"}
        </button>
        {onNext && <button type="button" className="btn" disabled={dirty.length > 0} onClick={onNext} title={dirty.length ? "Save your changes first" : ""}>{nextLabel ?? "Continue"}</button>}
        {unfinished > 0 && dirty.length === 0 && <span className="hint">{unfinished} polic{unfinished === 1 ? "y still has" : "ies still have"} placeholders. You can continue and fill them in later.</span>}
      </div>
    </div>
  );
}
