import StepDot from "./StepDot.jsx";

// Where a step stands: done once it is left behind (or, for the last step, once it has reached its goal), active while it is the one
// on screen, otherwise upcoming.
function stateOf(index, active, steps) {
  if (index < active) return "done";
  if (index > active) return "upcoming";
  return index === steps.length - 1 && steps[index].complete ? "done" : "active";
}

// The steps of a flow across the top of the page: a dot per step joined by lines that fill green as steps complete, with the name and a
// short status centred under each dot. steps: [{ key, label, summary?, busy?, progress?, complete? }]. A step in `reachable` (other than
// the active one) is a button, so the person can go back to it; the rest are not, so the stepper never skips ahead.
export default function Stepper({ steps, active, reachable, onSelect, label = "Progress" }) {
  const fill = (on) => <span aria-hidden className="step-line"><span className="step-line-fill" style={{ width: on ? "100%" : "0%" }} /></span>;
  return (
    <ol aria-label={label} className="stepper">
      {steps.map((step, index) => {
        const state = stateOf(index, active, steps);
        const navigable = index !== active && !!reachable?.has(index) && !!onSelect;
        const first = index === 0, last = index === steps.length - 1;
        const Tag = navigable ? "button" : "div";
        return (
          <li key={step.key} className="stepper-item">
            <Tag type={navigable ? "button" : undefined} onClick={navigable ? () => onSelect(index) : undefined}
              aria-current={index === active ? "step" : undefined} className={`stepper-hit${navigable ? " is-link" : ""}`}>
              <span className="stepper-track">
                {first ? <span className="step-line-gap" /> : fill(state !== "upcoming")}
                <StepDot state={state} number={index + 1} size="sm" busy={step.busy} progress={step.progress} />
                {last ? <span className="step-line-gap" /> : fill(state === "done")}
              </span>
              <span className={`stepper-label${state === "upcoming" ? " is-upcoming" : ""}`}>
                {step.label}{navigable ? <span className="sr-only"> (go back)</span> : null}
              </span>
              <span className="stepper-summary">{step.summary || " "}</span>
            </Tag>
          </li>
        );
      })}
    </ol>
  );
}
