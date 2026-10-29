import type { Step } from "../logic/steps";
export function Progress({ steps }: { steps: Step[] }) {
  return (
    <div className="steps">
      {steps.map((s) => (
        <div key={s.name} className={`step ${s.state}${s.waiting ? " waiting" : ""}`}>
          <div className="step-rail"><span className="step-node" /><span className="step-line" /></div>
          <div className="step-body"><div className="step-name">{s.name}</div><div className="step-sub">{s.sub}</div></div>
          <span className="step-check">{s.state === "done" ? "✓" : s.state === "failed" ? "✕" : ""}</span>
        </div>
      ))}
    </div>
  );
}
