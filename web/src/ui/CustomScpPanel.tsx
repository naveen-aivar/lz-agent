import type { Scope } from "../logic/design";
import { BasisBadge } from "./Basis";
import { useToast } from "./Toasts";
/** Policies the model wrote from the SOW. They are never applied by the generated code. */
export function CustomScpPanel({ scope }: { scope: Scope }) {
  const toast = useToast();
  const list = scope.customScps;
  async function copy(json: string) {
    try {
      await navigator.clipboard.writeText(json);
      toast("Policy copied");
    } catch (e) {
      toast(`Could not copy: ${e instanceof Error ? e.message : String(e)}`, "bad");
    }
  }
  return (
    <div>
      <div className="notice notice-info">
        <strong>Written by an AI model from the SOW.</strong> Review each policy against its quote, fill in its inputs, and test it on a
        non-production account first. The generated code never applies them: they ship in <code>custom-scps/</code>.
      </div>
      {!list.length && <div className="empty">This SOW has no requirements that need a custom policy beyond the catalog.</div>}
      {list.map((e) => {
        const json = JSON.stringify(e.policy, null, 2);
        const n = (e.policy.Statement ?? []).length;
        return (
          <div key={e.id} className="card scp">
            <div className="card-head">
              <div><h2>{e.title}</h2><div className="hint">{e.description}</div></div>
              <button type="button" className="btn btn-sm" onClick={() => void copy(json)}>Copy policy</button>
            </div>
            <div className="row"><code>{e.id}</code><span className="hint">attach to</span>{e.targets.map((t) => <span key={t} className="badge badge-blue">{t}</span>)}<BasisBadge basis={e.basis} /></div>
            {e.inputs.length > 0 && (
              <div className="row"><span className="hint">Fill in before use</span>{e.inputs.map((x) => <span key={x.name} className="badge badge-amber" title={x.description}>{x.name}</span>)}</div>
            )}
            {e.warnings.length > 0 && <div className="notice notice-warn" style={{ marginTop: 10 }}>{e.warnings.join(" ")}</div>}
            <details style={{ marginTop: 10 }}><summary>Policy JSON <span className="hint">{n} statement{n === 1 ? "" : "s"}</span></summary><pre><code>{json}</code></pre></details>
          </div>
        );
      })}
    </div>
  );
}
