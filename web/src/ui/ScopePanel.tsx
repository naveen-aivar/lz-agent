import type { ReactNode } from "react";
import type { Scope } from "../logic/design";
import { BasisBadge } from "./Basis";
const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;
function Limited<T>({ items, max, label, render }: { items: T[]; max: number; label: string; render: (x: T) => ReactNode }) {
  const head = items.slice(0, max), rest = items.slice(max);
  return (
    <>
      <ul className="items">{head.map(render)}</ul>
      {rest.length > 0 && <details><summary>Show all {items.length} {label}</summary><ul className="items">{rest.map(render)}</ul></details>}
    </>
  );
}
const Sec = ({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) => (
  <section className="sec"><h3>{title}{sub && <small>{sub}</small>}</h3>{children}</section>
);
const Codes = ({ list }: { list: string[] }) => <>{list.map((x) => <code key={x} className="gap-r">{x}</code>)}</>;
/** The approved design in plain sections. */
export function ScopePanel({ scope: s }: { scope: Scope }) {
  const created = "Created by the stacks from the email you provide";
  const r = s.regions, lg = s.logging;
  return (
    <div>
      <Sec title="Regions">
        <dl className="kv">
          <dt>Home</dt><dd><code>{r.home}</code></dd>
          <dt>Governed</dt><dd><Codes list={r.governed} /></dd>
          <dt>Also allowed</dt><dd>{r.extraAllowed.length ? <Codes list={r.extraAllowed} /> : "None"}</dd>
          <dt>Region deny</dt><dd>{r.enforceDeny ? `On: ${r.denied.length} regions denied (derived from the governed regions)` : "Off"}</dd>
        </dl>
        <details style={{ marginTop: 8 }}><summary>Denied regions</summary><p className="hint">{r.denied.join(", ")}</p></details>
      </Sec>
      <Sec title="Logging">
        <dl className="kv">
          <dt>Log retention</dt><dd>{lg.retentionDays} days</dd>
          <dt>Access log retention</dt><dd>{lg.accessLogRetentionDays} days</dd>
          <dt>Log archive account</dt><dd>{lg.logArchiveAccountId || created}</dd>
          <dt>Audit account</dt><dd>{lg.auditAccountId || created}</dd>
          <dt>Encryption key</dt><dd>{lg.kmsKeyArn || "Control Tower default"}</dd>
        </dl>
      </Sec>
      <Sec title="Organizational units" sub={plural(s.ous.length, "unit")}>
        <Limited items={s.ous} max={8} label="units" render={(o) => (
          <li key={o.name}><span className="main">{o.name}</span>{o.parent && <span className="meta">inside {o.parent}</span>}<BasisBadge basis={o.basis} /></li>)} />
      </Sec>
      <Sec title="Accounts" sub={plural(s.accounts.length, "account")}>
        <Limited items={s.accounts} max={8} label="accounts" render={(a) => (
          <li key={a.name}><span className="main">{a.name}</span><span className="meta">{a.kind} in {a.ou}{a.provisioning === "existing" ? ", already exists" : ""}</span><BasisBadge basis={a.basis} /></li>)} />
      </Sec>
      <Sec title="Service control policies from the catalog" sub={plural(s.scps.length, "policy", "policies")}>
        {s.scps.length ? <Limited items={s.scps} max={8} label="policies" render={(p) => (
          <li key={p.id}><code>{p.id}</code><span className="meta">on {p.targets.join(", ")}</span><BasisBadge basis={p.basis} /></li>)} /> : <p className="hint">None.</p>}
      </Sec>
      <Sec title="Control Tower controls" sub={`${s.summary.controls} controls, ${s.summary.controlAttachments} attachments`}>
        <Limited items={s.controls} max={6} label="controls" render={(c) => (
          <li key={c.id}><code>{c.id}</code><span className="meta">on {c.targets.join(", ")}</span><BasisBadge basis={c.basis} /></li>)} />
      </Sec>
      <Sec title="Not covered by the generated code" sub={plural(s.unsupported.length, "requirement")}>
        {s.unsupported.length ? <Limited items={s.unsupported} max={5} label="requirements" render={(u) => (
          <li key={u.requirement} className="block"><span className="main">{u.requirement}</span><div className="meta">{u.reason}</div></li>)} /> : <p className="hint">Every requirement is covered.</p>}
      </Sec>
      <Sec title="Assumptions">
        {s.assumptions.length ? <ul className="bullets">{s.assumptions.map((a) => <li key={a}>{a}</li>)}</ul> : <p className="hint">None.</p>}
      </Sec>
      <Sec title="Open questions" sub="to confirm with the customer">
        {s.openQuestions.length ? <ul className="bullets">{s.openQuestions.map((a) => <li key={a}>{a}</li>)}</ul> : <p className="hint">None.</p>}
      </Sec>
    </div>
  );
}
