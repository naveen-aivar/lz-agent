import { ACTIVE, iacItems, lzVersions, newestLz } from "../format.js";

// The steps of a run, as the stepper shows them: the requirements, then the two approval gates' work (landing zone,
// design) and the Landing Zone - IaC. Everything here is read from GET /runs/{id}; nothing is estimated.
export const STEP = { requirements: 0, landing: 1, design: 2, iac: 3 };
const DESIGN_STAGES = new Set(["start", "adr", "parallel", "review", "diagram", "usage"]);

// The step the run is working on (while it works) or waiting at (when it waits for the architect).
export function phaseOf(cur) {
  const { run } = cur;
  if (ACTIVE.has(run.status)) {
    const stage = run.stage === "starting" || run.stage === "queued" ? (run.lz && !run.lz_approved ? "lz" : "adr") : run.stage;
    if (stage === "ingest") return STEP.landing;
    if (stage === "lz") return STEP.landing;
    if (stage === "iac") return STEP.iac;
    if (DESIGN_STAGES.has(stage)) return STEP.design;
  }
  if ((cur.awaiting === "lz_approval" || !run.lz_approved) && lzVersions(cur).length) return STEP.landing;
  if (!(cur.versions || []).some((v) => v.approved_at)) return STEP.design;
  return STEP.iac;
}

// The design stage on screen while a version is made, for the picture and the progress.
export const activeStage = (run) => (ACTIVE.has(run.status) ? (run.stage === "starting" || run.stage === "queued" ? "start" : run.stage) : null);

export function flowOf(cur) {
  const { run } = cur;
  const working = ACTIVE.has(run.status);
  const active = phaseOf(cur);
  const progress = working && typeof run.progress === "number" ? Math.min(1, Math.max(0, run.progress / 100)) : undefined;

  const lz = lzVersions(cur);
  const newest = newestLz(cur);
  const lastLz = lz[lz.length - 1];
  const lzSummary = working && active === STEP.landing ? "Designing"
    : lastLz?.status === "failed" && !newest ? "Failed"
      : newest && Number(run.lz_approved) === newest.lz ? `Landing zone ${newest.lz} approved`
        : newest ? `Landing zone ${newest.lz} waits for you` : undefined;

  const versions = cur.versions || [];
  const latest = versions[versions.length - 1];
  const approvedV = versions.filter((v) => v.approved_at).pop();
  const designSummary = working && active === STEP.design ? `Version ${latest?.version ?? 1} in progress`
    : approvedV ? `Version ${approvedV.version} approved`
      : latest?.status === "failed" && !run.latest_complete_version ? "Failed"
        : run.latest_complete_version ? `Version ${run.latest_complete_version} waits for you` : undefined;

  const iac = approvedV ? iacItems(cur, approvedV) : [];
  const lastIac = iac[iac.length - 1];
  const iacApproved = (cur.iac || cur.landing_zones || []).some((x) => x.approved_at);
  const iacSummary = working && active === STEP.iac ? "Generating"
    : iacApproved ? "Approved" : lastIac?.status === "failed" ? "Failed"
      : lastIac?.status === "completed" ? `IaC ${lastIac.iac} waits for you` : undefined;

  const step = (index, key, label, summary) => ({
    key, label, summary,
    busy: working && index === active,
    progress: working && index === active ? progress : undefined,
    complete: index === STEP.iac && iacApproved,
  });
  return {
    working, active, progress,
    steps: [
      step(STEP.requirements, "requirements", "Requirements", run.input_kind === "file" ? "From a file" : "Pasted text"),
      step(STEP.landing, "landing", "Landing zone", lzSummary),
      step(STEP.design, "design", "Design", designSummary),
      step(STEP.iac, "iac", "IaC", iacSummary),
    ],
  };
}

// The words for one stage, in the order the agent works: what the picture says while it runs.
export const STAGE_TEXT = {
  start: "Starting the work.",
  ingest: "Reading the requirements file.",
  lz: "Designing the landing zone: accounts, OUs, network and guardrails, then its diagram.",
  adr: "Writing the decision record within the landing zone.",
  parallel: "Reviewing against the Well-Architected Framework, drawing the diagram and estimating usage, all at once.",
  review: "Reviewing the design against the Well-Architected Framework.",
  diagram: "Drawing the architecture diagram.",
  usage: "Estimating the monthly usage per service.",
  iac: "Generating the Terraform and CloudFormation for the landing zone.",
};
