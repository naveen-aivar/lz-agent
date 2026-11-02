import { useState } from "react";
import { Check } from "lucide-react";

// The circle in the stepper: the step number, or a green tick once the step is done. While the active step reports `progress`, a blue
// ring runs clockwise round the circle as the work advances; when it closes the circle turns green and ticks. Without `progress`, a
// busy active step shows a pulsing ring instead. (The portal's StepDot, in plain JSX and CSS.)

const RING_MS = 700;                    // how long the ring takes to catch up with a new `progress`
const CLOSE_DELAY_MS = RING_MS - 100;   // a ring that has just closed turns green a beat before it finishes drawing
const BORDER = 2;                       // thickness of the dot's border, px
// The dot's width in px and the width of the light-blue band round it (the empty track of the ring); keep in step with .step-dot-* in stepper.css.
const SIZE = { md: { px: 34, halo: 5 }, sm: { px: 28, halo: 4 } };

const clampLevel = (progress) => (Number.isFinite(progress) ? Math.min(1, Math.max(0, progress)) : 0);

export default function StepDot({ state, number, size = "md", busy = false, progress }) {
  const level = progress === undefined ? undefined : clampLevel(progress);
  const complete = state === "done" || (state === "active" && level === 1);
  const ringing = state === "active" && level !== undefined && level < 1;
  // A dot that was already complete when it appeared (a step revisited) just shows the tick; one that closes its ring on screen waits for the ring.
  const [startedComplete] = useState(complete);
  const closing = complete && !startedComplete && level !== undefined;
  const { px, halo } = SIZE[size];

  return (
    <span className="step-dot-wrap">
      {state === "active" && busy && !complete && !level ? <span aria-hidden className="step-dot-pulse" /> : null}
      <span style={closing ? { transitionDelay: `${CLOSE_DELAY_MS}ms` } : undefined}
        className={`step-dot step-dot-${size} is-${complete ? "done" : state}${ringing ? " is-ringing" : ""}`}>
        {complete && !closing ? null : (
          <span aria-hidden={complete} className={`step-dot-num${complete ? " is-hidden" : ""}`} style={complete ? { transitionDelay: `${CLOSE_DELAY_MS}ms` } : undefined}>{number}</span>
        )}
        {complete ? <Check className={`step-dot-check${closing ? " is-closing" : ""}`} size={size === "sm" ? 14 : 16} strokeWidth={2.25} aria-hidden
          style={closing ? { animationDelay: `${CLOSE_DELAY_MS}ms` } : undefined} /> : null}
        {state === "active" && level !== undefined ? <ProgressRing level={level} px={px} halo={halo} hidden={complete} /> : null}
      </span>
    </span>
  );
}

// The dark-blue arc that fills the light-blue band round the dot: it starts at the top and runs clockwise. `pathLength` makes the circle 100
// units round whatever its size, so the dash is simply a percentage.
function ProgressRing({ level, px, halo, hidden }) {
  const remaining = Math.round((1 - level) * 1000) / 10;
  const box = px + halo * 2;
  return (
    <svg role="progressbar" aria-label="Step progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(level * 100)}
      viewBox={`0 0 ${box} ${box}`} className="step-ring" style={{ inset: -(BORDER + halo) }}>
      <circle cx={box / 2} cy={box / 2} r={(px + halo) / 2} fill="none" stroke="currentColor" strokeWidth={halo} strokeLinecap="round"
        pathLength={100} strokeDasharray={100} strokeDashoffset={remaining} opacity={level > 0 && !hidden ? 1 : 0}
        style={{ transition: `stroke-dashoffset ${RING_MS}ms ease-out, opacity 150ms ease-out ${hidden ? CLOSE_DELAY_MS : 0}ms` }} />
    </svg>
  );
}
