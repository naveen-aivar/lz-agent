import { Check, FileCode2, FileText, TriangleAlert } from "lucide-react";
import { ACTIVE, iacItems, lzVersions, timeOf } from "../format.js";
import { STAGE_TEXT, STEP, activeStage } from "./flow.js";
import { clock, useElapsed } from "./useElapsed.js";

// The agent at work, for this agent: a blueprint sheet whose parts check in as the agent makes them, and beside it the
// agent's own log for this step as a timeline. Every part is bound to what GET /runs/{id} reports (the stage, the
// files written, the log lines); nothing moves without progress. One ambient motion at most: a soft pulse on the part
// being made. A failed part shows a quiet warning; the clock shows how long the step has taken so far.

// The parts each step makes, and the stage that makes each one (null: the whole step makes it, so it checks in at the end).
const PARTS = {
  [STEP.landing]: { title: "Landing zone", icon: FileText, parts: [
    ["lz", "Accounts and OUs"], ["lz", "Network and guardrails"], ["lz", "Account map and OU tree"]] },
  [STEP.design]: { title: "Design", icon: FileText, parts: [
    ["adr", "Decision record"], ["review", "Well-Architected review"], ["diagram", "Architecture diagram"], ["usage", "Usage estimate"]] },
  [STEP.iac]: { title: "Landing Zone - IaC", icon: FileCode2, parts: [
    ["iac", "Scope"], ["iac", "Terraform"], ["iac", "CloudFormation"]] },
};

// What this step is working on: its item (landing zone, version or IaC), when it started, and whether it failed.
function phaseItem(cur, phase) {
  if (phase === STEP.landing) return lzVersions(cur).pop();
  const versions = cur.versions || [];
  if (phase === STEP.design) return versions[versions.length - 1];
  const approved = versions.filter((v) => v.approved_at).pop();
  return approved ? iacItems(cur, approved).pop() : null;
}

// A design part checks in from its own field on the version (the review, diagram and usage run in parallel once the
// decision record is written, so each one ticks as it finishes, in any order).
function partState(phase, item, partStage) {
  if (!item) return "waiting";
  if (phase !== STEP.design) {
    if (item.status === "failed") return "failed";
    return item.status === "completed" || item.status === "partial" ? "done" : "pending";   // one model step makes them all
  }
  const field = { adr: item.adr, review: item.review, diagram: item.diagram, usage: item.usage }[partStage];
  if (field?.status === "failed") return "failed";
  if (field) return "done";
  if (!ACTIVE.has(item.status)) return item.status === "failed" ? "waiting" : "done";
  return partStage === "adr" || item.adr ? "making" : "waiting";
}

export default function AgentAtWork({ cur, phase }) {
  const working = ACTIVE.has(cur.run.status);
  const stage = activeStage(cur.run);
  const item = phaseItem(cur, phase);
  const started = item ? Date.parse(item.created_at) / 1000 : null;
  const elapsed = useElapsed(Number.isFinite(started) ? started : null, working);
  const sheet = PARTS[phase] || PARTS[STEP.design];
  const Icon = sheet.icon;
  const log = (cur.log || []).filter((l) => item && Date.parse(l.at) >= Date.parse(item.created_at) - 1000).slice(-8);
  const failed = item?.status === "failed";
  const sentence = failed ? "This step did not finish. The reason is below." : working ? STAGE_TEXT[stage] || STAGE_TEXT.start : "Done. The results are below.";

  return (
    <div className="aaw">
      <div className="aaw-head">
        <p role="status" className="aaw-status">{sentence}</p>
        {working && elapsed != null ? <p className="tone-muted aaw-clock">Elapsed {clock(elapsed)}</p> : null}
      </div>
      <div className="aaw-body">
        <div className={`sheet${!working && !failed ? " sheet-done" : ""}`}>
          <p className="sheet-title">
            <Icon size={16} aria-hidden className="tone-info" /> {sheet.title}
            {working && phase !== STEP.design ? <span aria-hidden className="working-dot" /> : null}
          </p>
          <ul className="sheet-parts" aria-label={`Parts of the ${sheet.title.toLowerCase()}`}>
            {sheet.parts.map(([partStage, label]) => {
              const state = partState(phase, item, partStage);
              return (
                <li key={label} className={`sheet-part is-${state}`}>
                  <span aria-hidden className="sheet-mark">
                    {state === "done" ? <Check size={12} strokeWidth={2.5} /> : state === "failed" ? <TriangleAlert size={12} /> : null}
                  </span>
                  <span className="sheet-label">{label}</span>
                  <span className="sr-only">{state === "done" ? ", done" : state === "making" || state === "pending" ? ", being made" : state === "failed" ? ", failed" : ", waiting"}</span>
                </li>
              );
            })}
          </ul>
        </div>
        <ol className="timeline" aria-label="What the agent did" tabIndex={0}>
          {log.map((l) => (
            <li key={`${l.at}-${l.message}`} className={`tl-item${l.level === "warning" || l.level === "error" ? " is-warn" : ""}`}>
              <span aria-hidden className="tl-dot" />
              <span className="tl-text">{l.message}</span>
              <span className="tl-time">{timeOf(l.at)}</span>
            </li>
          ))}
          {working ? <li className="tl-item tl-next"><span aria-hidden className="tl-dot" /><span className="tl-text">Working on the next step</span></li> : null}
        </ol>
      </div>
    </div>
  );
}
