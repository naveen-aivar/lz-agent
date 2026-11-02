import { Button } from "./Button.jsx";

// A step's forward button (Save run, Open the baseline, Review account). It starts pale, like a disabled button, and fills with colour from
// left to right as the step's requirements are met or the agent's work gets done. Once the step is ready it works at once, and when the
// fill has finished a ring pulses out from it and its arrow nudges forward. It cannot be used before the step is ready, so there is no
// way past an unmet requirement or a run still in progress. (The portal's StepNextButton, in plain JSX and CSS.)

const FILL_MS_ALL_OR_NOTHING = 1200; // a step with one thing to do fills slowly once it is done, so the change is easy to see
const FILL_MS_WITH_PROGRESS = 600;   // a step that reports how far it has got fills at a steady pace as that number moves
const MAX_UNFINISHED_FILL = 0.96;    // until the step is ready the fill stops short, so a completely full button always means "go"

/** How much of the button is filled, 0 to 1. A ready button is full; otherwise it shows `progress` (held just short of full). */
export function fillLevel(ready, loading, progress) {
  if (ready) return 1;
  if (progress === undefined || !Number.isFinite(progress)) return loading ? 1 : 0;
  return Math.min(Math.max(progress, 0), MAX_UNFINISHED_FILL);
}

// ready: the step is done and may be left (the only thing that enables the button). progress: how far the step has got, 0 to 1; leave it
// out when the step is all or nothing. working: the agent is busy with the step, so a soft sheen crosses the filled part.
export default function StepNextButton({ ready, progress, working = false, loading = false, className = "", style, children, ...rest }) {
  const level = fillLevel(ready, loading, progress);
  const fillMs = progress === undefined ? FILL_MS_ALL_OR_NOTHING : FILL_MS_WITH_PROGRESS;
  const shining = working && !ready && level > 0;
  return (
    <Button {...rest} variant="step" loading={loading} disabled={!ready} data-solid={level === 1 || undefined}
      className={`${ready && !loading ? "next-ready " : ""}${className}`.trim()} style={{ ...style, "--next-fill-ms": `${fillMs}ms` }}>
      <span aria-hidden data-fill className={`step-fill${shining ? " step-fill-shine" : ""}`} style={{ width: `${level * 100}%` }} />
      {children}
    </Button>
  );
}
