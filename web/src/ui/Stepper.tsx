import type { JourneyStep, StepId } from "../logic/journey";
/** The steps of a project. A step that is not open yet is shown but cannot be clicked. */
export function Stepper({ steps, onGo }: { steps: JourneyStep[]; onGo: (id: StepId) => void }) {
  return (
    <ol className="stepper" aria-label="Steps">
      {steps.map((s, i) => (
        <li key={s.id} className={`stp ${s.state}`}>
          <button type="button" disabled={!s.open} aria-current={s.state === "current" ? "step" : undefined} onClick={() => onGo(s.id)}>
            <span className="stp-n">{s.state === "done" ? "✓" : i + 1}</span><span className="stp-l">{s.label}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}
