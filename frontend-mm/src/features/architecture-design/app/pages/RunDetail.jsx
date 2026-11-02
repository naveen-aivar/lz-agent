import { useEffect, useRef, useState } from "react";
import { ArrowRight, ScrollText } from "lucide-react";
import { api } from "../api.js";
import { INFO } from "../info.js";
import { ACTIVE, IAC_NAME, ago, iacItems, isDone, lzVersions, newestLz, num, selectedVersion, timeOf, when } from "../format.js";
import { refreshAll, usePoll } from "../usePoll.js";
import { href } from "../useRoute.js";
import ConfirmDialog from "../components/ConfirmDialog.jsx";
import ReviseDialog from "../components/ReviseDialog.jsx";
import { ErrorNotice, StatusBadge } from "../components/bits.jsx";
import { Button, ButtonLink } from "../components/ui/Button.jsx";
import { Card } from "../components/ui/Card.jsx";
import InfoHint from "../components/ui/InfoHint.jsx";
import { KpiTile } from "../components/ui/KpiTile.jsx";
import { Modal } from "../components/ui/Modal.jsx";
import { Notice } from "../components/ui/Notice.jsx";
import { PageHeader } from "../components/ui/PageHeader.jsx";
import { SkeletonText } from "../components/ui/Skeleton.jsx";
import StepNextButton from "../components/ui/StepNextButton.jsx";
import Stepper from "../components/ui/Stepper.jsx";
import AgentAtWork from "../run/AgentAtWork.jsx";
import DesignStep, { DESIGN_TABS } from "../run/DesignStep.jsx";
import IacStep, { iacFlags } from "../run/IacStep.jsx";
import LandingZoneStep from "../run/LandingZoneStep.jsx";
import { STEP, flowOf } from "../run/flow.js";
import { useLingering } from "../run/useElapsed.js";

const quotaChanged = () => window.dispatchEvent(new Event("quota:changed"));
// The output tab asked for in the address (#/runs/<id>/<tab>), the way the old console's #hash picked it.
const tabFromHash = () => { const t = window.location.hash.split("/")[3]; return DESIGN_TABS.includes(t) ? t : null; };

// The page while the run is fetched: the header from the list of runs, the stepper and a row of tiles in their places.
function RunSkeleton({ listRun }) {
  return (
    <>
      <PageHeader title={listRun?.title || <SkeletonText>Billing dispute assistant</SkeletonText>}
        actions={<button type="button" className="btn btn-step btn-md" data-solid="true" disabled aria-hidden tabIndex={-1}><SkeletonText>Approve landing zone 1</SkeletonText></button>}>
        <p className="page-meta"><SkeletonText>Ready</SkeletonText><SkeletonText>Started 28 Oct 2026, 15:27 (2h ago)</SkeletonText><SkeletonText>from pasted text · 1,677 characters</SkeletonText><SkeletonText>Ref 94e8e036</SkeletonText></p>
      </PageHeader>
      <div className="stack">
        <Card><Stepper active={1} steps={[{ key: "r", label: "Requirements", summary: "Pasted text" }, { key: "l", label: "Landing zone", summary: " " }, { key: "d", label: "Design" }, { key: "i", label: "IaC" }]} /></Card>
        <div className="toolbar step-toolbar"><SkeletonText>Landing zone 1</SkeletonText><SkeletonText>Ready</SkeletonText><SkeletonText>standard tier</SkeletonText></div>
        <div className="kpi-grid kpi-grid-5">{[0, 1, 2, 3, 4].map((i) => <KpiTile key={i} loading label="" value="" hint="" index={i} />)}</div>
      </div>
    </>
  );
}

export default function RunDetail({ id, listRun }) {
  const [fast, setFast] = useState(true);
  const view = usePoll(() => api.run(id), { ms: fast ? 2000 : 15000, deps: [id, fast] });
  const cur = view.data ? { lz_versions: [], versions: [], iac: [], ...view.data } : null;
  const working = !!cur && ACTIVE.has(cur.run.status);

  // Poll about every 2 s while the run works, every 15 s while it waits; when it ends, the rest of the app catches up.
  const wasWorking = useRef(false);
  useEffect(() => {
    setFast(!cur || working);
    if (wasWorking.current && cur && !working) refreshAll();
    if (cur) wasWorking.current = working;
  }, [working, !!cur]); // eslint-disable-line react-hooks/exhaustive-deps

  const [stepView, setStepView] = useState(null);   // the step on screen when the architect picked one (null: the run's own)
  const [lzPick, setLzPick] = useState(null);
  const [vPick, setVPick] = useState(null);
  const [iacPick, setIacPick] = useState(null);
  const [tab, setTab] = useState(() => tabFromHash() || "diagram");
  const [tabChosen, setTabChosen] = useState(() => !!tabFromHash());
  const [confirm, setConfirm] = useState(null);
  const [lzRevise, setLzRevise] = useState(null);   // null, or { initial }
  const [designRevise, setDesignRevise] = useState(false);
  const [iacRevise, setIacRevise] = useState(null); // null, or { base, scope }
  const [logOpen, setLogOpen] = useState(false);

  const flow = cur ? flowOf(cur) : null;
  const phase = flow?.active;
  // A new step of the run takes the screen back from the architect's pick, and follows the work.
  useEffect(() => { setStepView(null); }, [phase]);
  const lastWorkPhase = useRef(null);
  if (working) lastWorkPhase.current = phase;
  const showWork = useLingering(working);

  if (view.error && !cur) {
    if (String(view.error).includes("not found")) {
      return <Notice tone="warning" title="That run does not exist." action={<ButtonLink variant="secondary" size="sm" href={href("runs")}>Back to the runs</ButtonLink>}>It may have been removed, or the address is wrong.</Notice>;
    }
    return <ErrorNotice what="this run" detail={view.error} onRetry={view.refresh} />;
  }
  if (!cur) return <RunSkeleton listRun={listRun} />;

  const { run } = cur;
  const shown = stepView ?? phase;
  const v = selectedVersion(cur, vPick);
  const afterStart = () => { setStepView(null); setLzPick(null); setVPick(null); setIacPick(null); view.refresh(); quotaChanged(); };
  const designTab = tabChosen ? tab : "diagram";

  // ── the decisions and starts, each asked first ──────────────────────────────────────────────────────────────────
  const approveLz = (n) => setConfirm({
    title: `Approve landing zone ${n}?`,
    text: (cur.versions || []).length ? "Design versions that follow an older landing zone are marked out of date; re-align the design next."
      : "The design starts against it: decision record, Well-Architected review, architecture diagram and usage estimate (about 3 model calls).",
    label: "Approve", failTitle: "Not approved.",
    run: async () => {
      const res = await api.lzApprove(run.run_id, n);
      afterStart();
      return res.adr_error ? { title: "Approved, but the design did not start.", description: res.adr_error, variant: "warning" } : `Landing zone ${n} approved.`;
    },
  });
  const retryLz = () => setConfirm({
    title: "Design the landing zone again?", text: "The agent designs landing zone 1 again from the requirements (1 to 3 model calls).",
    label: "Start", failTitle: "Not started.",
    run: async () => { const res = await api.lzRetry(run.run_id); afterStart(); return `Landing zone ${res.lz} started.`; },
  });
  const approveVersion = (n) => setConfirm({
    title: `Approve version ${n}?`, text: `This also generates its ${IAC_NAME} (Terraform and CloudFormation).`,
    label: "Approve", failTitle: "Not approved.",
    run: async () => { await api.approve(run.run_id, n); afterStart(); return `Version ${n} approved.`; },
  });
  const realign = (lz) => setConfirm({
    title: `Re-align to landing zone ${lz}?`, text: `A new version re-runs the design within landing zone ${lz}: the decision record, the Well-Architected review, the diagram and the usage estimate (3 model calls).`,
    label: "Start", failTitle: "Not started.",
    run: async () => { const res = await api.revise(run.run_id, {}); afterStart(); return `Version ${res.version} started.`; },
  });
  const startIac = (version) => setConfirm({
    title: `Generate the ${IAC_NAME}?`, text: `Terraform and CloudFormation for version ${version}, from its landing zone. Claude writes only the custom SCPs.`,
    label: "Generate", failTitle: "Not started.",
    run: async () => { await api.iacStart(run.run_id, version); afterStart(); return `${IAC_NAME} 1 started.`; },
  });
  const approveIac = (version, n) => setConfirm({
    title: `Approve ${IAC_NAME} ${n}?`, text: `It becomes the hand-off of version ${version} to the Landing Zone agent.`,
    label: "Approve", failTitle: "Not approved.",
    run: async () => { await api.iacApprove(run.run_id, version, n); afterStart(); return `${IAC_NAME} ${n} approved.`; },
  });
  const reviseLandingZone = (text) => { setStepView(STEP.landing); setLzRevise({ initial: text }); };

  // ── the one forward button, for the step on screen ──────────────────────────────────────────────────────────────
  const pale = (label) => ({ label, ready: false, progress: flow.progress, working: !showWork });
  const goTo = phase > shown ? { label: `Go to ${flow.steps[phase].label.toLowerCase() === "iac" ? "the IaC" : `the ${flow.steps[phase].label.toLowerCase()}`}`, ready: true, onClick: () => setStepView(null) } : null;
  let forward = null;
  if (shown === STEP.landing) {
    const lz = lzVersions(cur);
    const newest = newestLz(cur);
    if (working && phase === STEP.landing) forward = pale("Approve the landing zone");
    else if (newest && !newest.approved_at && !working) forward = { label: `Approve landing zone ${newest.lz}`, ready: true, onClick: () => approveLz(newest.lz) };
    else if (!newest && lz[lz.length - 1]?.status === "failed" && !working) forward = { label: "Design the landing zone again", ready: true, onClick: retryLz };
    else forward = goTo;
  } else if (shown === STEP.design) {
    if (working && phase === STEP.design) forward = pale("Approve the version");
    else if (isDone(v) && !v.approved_at && !v.stale_lz && !working) forward = { label: `Approve version ${v.version}`, ready: true, onClick: () => approveVersion(v.version) };
    else forward = goTo;
  } else if (shown === STEP.iac && v) {
    const items = iacItems(cur, v);
    const last = items[items.length - 1];
    const item = items.find((x) => x.iac === iacPick) || last;
    const anyDone = items.some((x) => x.status === "completed");
    if (working && phase === STEP.iac) forward = pale("Approve the IaC");
    else if (v.approved_at && !working && !v.stale_lz && (!items.length || (last.status === "failed" && last.iac === 1 && !anyDone))) {
      forward = { label: `Generate the ${IAC_NAME}`, ready: true, onClick: () => startIac(v.version) };
    } else if (item && item.status === "completed" && !item.approved_at && !working) forward = { label: `Approve IaC ${item.iac}`, ready: true, onClick: () => approveIac(v.version, item.iac) };
  }

  const reachable = new Set([STEP.landing, STEP.design, STEP.iac].filter((i) => i <= phase));
  const title = v?.title || run.title || run.srs_filename || "Untitled";
  const newest = newestLz(cur);
  const iacBase = iacRevise?.base;

  return (
    <>
      <PageHeader title={title}
        actions={forward ? (
          <StepNextButton ready={forward.ready} progress={forward.progress} working={forward.working} onClick={forward.onClick}>
            {forward.label} <ArrowRight size={16} aria-hidden />
          </StepNextButton>
        ) : null}>
        <p className="page-meta">
          <StatusBadge status={run.status} />
          <span>Started {when(run.created_at)} ({ago(run.created_at)})</span>
          <span>{run.input_kind === "file" ? `from ${run.srs_filename}` : "from pasted text"}{run.input_chars ? ` · ${num(run.input_chars)} characters` : ""}</span>
          <span className="mono tone-muted" title={`The reference of this run: ${run.run_id}`}>Ref {run.run_id.slice(0, 8)}</span>
        </p>
      </PageHeader>

      <div className="stack">
        <Card className="stepper-card">
          <div className="stepper-row">
            <Stepper label="Steps of this run" steps={flow.steps.map((s) => (showWork ? { ...s, busy: false } : s))} active={phase} reachable={reachable}
              onSelect={(i) => setStepView(i === phase ? null : i)} />
            <div className="stepper-side">
              <InfoHint {...INFO.flow} />
              <Button variant="tertiary" size="sm" onClick={() => setLogOpen(true)}><ScrollText size={16} aria-hidden /> Agent log</Button>
            </div>
          </div>
        </Card>

        {showWork && (lastWorkPhase.current ?? phase) === shown ? (
          <Card title="The agent at work" aside={working ? "Working" : "Finished"} className="animate-fade-in">
            <AgentAtWork cur={cur} phase={lastWorkPhase.current ?? phase} />
          </Card>
        ) : null}

        {run.status === "failed" && run.error && !(cur.versions || []).length && !lzVersions(cur).length
          ? <Notice tone="danger" title="The run did not start.">{run.error}</Notice> : null}

        <div key={shown} className="step-enter">
          {shown === STEP.landing ? <LandingZoneStep cur={cur} pick={lzPick} setPick={setLzPick} onRevise={(initial) => setLzRevise({ initial })} /> : null}
          {shown === STEP.design ? (
            <DesignStep cur={cur} v={v} setPick={setVPick} tab={designTab} setTab={(t) => { setTab(t); setTabChosen(true); }}
              onRevise={() => setDesignRevise(true)} onRealign={realign} onOpenLandingZone={() => setStepView(STEP.landing)}
              onReviseLandingZone={reviseLandingZone} onNewVersion={afterStart} />
          ) : null}
          {shown === STEP.iac ? (
            <IacStep cur={cur} v={v} pick={iacPick} setPick={setIacPick} onRevise={(base, scope) => setIacRevise({ base, scope })}
              onOpenLandingZone={() => setStepView(STEP.landing)} />
          ) : null}
        </div>
      </div>

      <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />
      <ReviseDialog open={!!lzRevise} onClose={() => setLzRevise(null)} idPrefix="lzd" initial={lzRevise?.initial || ""}
        title="Revise the landing zone" label="Revise the landing zone" flags={newest?.flags}
        description={`A revision is a new landing zone of this run (1 model call, a second only for blocking errors)${(cur.versions || []).length ? "; the design versions are then out of date until you approve it and re-align them" : ""}.`}
        placeholder="e.g. Add a Sandbox OU, use central NAT egress, or add a DR region ap-south-2 for prod."
        tooShort="Say what to change in the landing zone."
        run={async (text) => { const res = await api.lzRevise(run.run_id, text); afterStart(); return `Landing zone ${res.lz} started from landing zone ${newest?.lz}.`; }} />
      <ReviseDialog open={designRevise} onClose={() => setDesignRevise(false)} idPrefix="design"
        title="Revise the design" label="Create new version"
        description="A new version re-runs the decision record within the approved landing zone, the Well-Architected review, the diagram and the usage estimate (3 model calls)."
        placeholder="e.g. Use Aurora Serverless v2 instead of RDS, and make the database Multi-AZ."
        tooShort="Say what to change in the design."
        run={async (text) => { const res = await api.revise(run.run_id, { instruction: text }); afterStart(); return `Version ${res.version} started.`; }} />
      <ReviseDialog open={!!iacRevise} onClose={() => setIacRevise(null)} idPrefix="iac"
        title={`Revise the ${IAC_NAME}`} label={`Revise the ${IAC_NAME}`} flags={iacFlags(iacRevise?.scope)}
        description="Custom SCPs only. OUs, accounts, Regions, guardrails and the network come from the approved landing zone: change those in the landing zone."
        placeholder="e.g. Add a custom SCP that denies deleting GuardDuty detectors in the Workloads OU."
        tooShort="Say which custom SCPs to change."
        run={async (text) => { const res = await api.iacRevise(run.run_id, v.version, text); afterStart(); return `${IAC_NAME} ${res.iac} started from ${IAC_NAME} ${iacBase?.iac}.`; }} />
      <Modal open={logOpen} onOpenChange={setLogOpen} title="Agent log" description="Every step the agent took for this run, newest first." size="lg">
        {(cur.log || []).length ? (
          <div className="log-box" tabIndex={0} role="region" aria-label="Agent log entries"><ol className="log fade-list">
            {(cur.log || []).slice().reverse().map((l) => (
              <li key={`${l.at}-${l.stage}-${l.message}`} className={`log-item lvl-${l.level}`}>
                <span className="log-stage">{l.stage}</span><span className="log-msg">{l.message}</span><span className="log-time">{timeOf(l.at)}</span>
              </li>
            ))}
          </ol></div>
        ) : <p className="tone-muted">Nothing logged yet.</p>}
      </Modal>
    </>
  );
}
