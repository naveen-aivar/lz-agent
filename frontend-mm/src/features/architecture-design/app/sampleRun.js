// Saved sample run (ported unchanged from deployment/ui/replay.js): plays back a recorded run (sample_run/bundle.json, built by scripts/build_sample_run.py) through
// the same API shapes the console reads, so the normal rendering code shows it. The flow is the real one: landing
// zone 1 plays (3-5 s) and waits for approval; approving it plays design version 1 (the ADR 3-5 s, then the review,
// diagram and usage at the same time, as the worker runs them); "Apply findings" plays version 2; approving a version plays the recorded Landing Zone - IaC for it. Outputs, counts and log
// lines are the recorded ones (see the bundle's "note"). State lives in sessionStorage so a reload keeps the run.
function makeSampleRun() {
  const RUN_ID = "sample-run";
  const BUNDLE_URL = "/agents/architecture-design/sample_run/bundle.json";
  const KEY = "archSampleRun";
  // stage, progress shown while it runs, files the stage writes, version field it fills; after the ADR the other three
  // run in parallel (stage "parallel", progress 45 plus a share for each one that finished)
  const PLAN = [
    ["adr", 15, ["adr.md", "spec.json", "summary.json", "design.json"], "adr"],
    ["review", 45, ["wa_review.json", "wa_chart.json", "wa_review.md"], "review"],
    ["diagram", 70, ["architecture.png", "architecture.svg", "architecture.drawio", "report.json"], "diagram"],
    ["usage", 82, ["usage.json", "usage_assumptions.md"], "usage"],
  ];
  let bundle = null;

  const load = async () => {
    if (!bundle) {
      const resp = await fetch(BUNDLE_URL);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      bundle = await resp.json();
    }
    return bundle;
  };
  const s0 = () => readState() || {};
  const readState = () => { try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch { return null; } };
  const writeState = (s) => { try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch { /* private mode */ } };
  const iso = (ms) => new Date(ms).toISOString();
  const between = (lo, hi) => Math.round(lo + Math.random() * (hi - lo));
  const fail = (status, message) => { const e = new Error(message); e.status = status; throw e; };
  const span = (from) => ({ start: from, end: from + between(3000, 5000) });

  function schedule(start) {
    // [stage, starts at, ends at] for one design version: the ADR, then the other three from the same moment
    const t = start + between(600, 1200);
    const adrEnd = t + between(3000, 5000);
    return PLAN.map(([stage]) => (stage === "adr" ? [stage, t, adrEnd]
      : [stage, adrEnd, adrEnd + (stage === "diagram" ? between(2000, 3000) : between(3000, 5000))]));
  }
  const planEnd = (plan) => Math.max(...plan.map(([, , to]) => to));

  function versionAt(saved, plan, now) {
    const v = { ...saved, files: {}, status: "running", stage: "starting" };
    delete v.adr; delete v.review; delete v.diagram; delete v.usage;
    delete v.seconds; delete v.finished_at;
    let progress = 5;
    for (const [i, [stage, from, to]] of plan.entries()) {
      if (now < from) break;
      v.stage = stage === "adr" ? "adr" : "parallel";
      progress = stage === "adr" ? PLAN[i][1] : progress + (now >= to ? 17 : 0);
      if (now >= to) {
        for (const n of PLAN[i][2]) if (saved.files && saved.files[n] !== undefined) v.files[n] = saved.files[n];
        if (saved[PLAN[i][3]] !== undefined) v[PLAN[i][3]] = saved[PLAN[i][3]];
      }
      if (stage === "adr" && now >= to) progress = 45;
    }
    const end = planEnd(plan);
    if (now >= end) Object.assign(v, saved, { files: { ...saved.files } });
    return { v, progress, done: now >= end, end };
  }

  function versionLog(b, n, plan, start, now) {
    // the recorded lines of version n, re-timed onto the playback: a stage's first line when it starts, the rest when
    // it ends
    const windows = Object.fromEntries(plan.map(([s, from, to]) => [s, [from, to]]));
    const end = planEnd(plan);
    const seen = new Set();
    const out = [];
    for (const l of b.log.filter((x) => x.version === n)) {
      let at = start;
      if (windows[l.stage]) {
        const [from, to] = windows[l.stage];
        at = seen.has(l.stage) ? to - 50 : from;
        seen.add(l.stage);
      } else if (l.stage === "done") at = end;
      if (at <= now) out.push({ ...l, at: iso(at) });
    }
    return out;
  }

  // a landing-zone or IaC step: running between start and end, then the recorded item
  function stepAt(saved, timing, now, approvedAt) {
    const done = now >= timing.end;
    const item = done ? { ...saved, finished_at: iso(timing.end) } : { ...saved, status: "running", files: {} };
    delete item.counts; if (done) item.counts = saved.counts;
    item.created_at = iso(timing.start);
    if (done && approvedAt) { item.approved_at = approvedAt; item.approved_by = "Web user"; }
    return { item, done };
  }
  const stepLog = (lines, timing, now) => lines.map((l, i) => ({ ...l, at: iso(i === 0 ? timing.start : timing.end) }))
    .filter((l) => Date.parse(l.at) <= now);

  async function runState() {
    const b = await load();
    const s = readState();
    if (!s) fail(404, "run not found");
    const now = Date.now();
    let log = [];
    const run = { ...b.run, run_id: RUN_ID, created_at: iso(s.lz.start), version: s.started.length,
      lz: 1, status: "completed", stage: "done", progress: 100 };
    const busy = (stage, progress) => Object.assign(run, { status: "running", stage, progress, finished_at: null });

    const lz = stepAt(b.lz[0].item, s.lz, now, s.lzApproved);
    log = log.concat(stepLog(b.lz[0].log, s.lz, now));
    if (!lz.done) busy("lz", 20);
    else run.latest_complete_lz = 1;
    if (s.lzApproved) {
      run.lz_approved = 1;
      log.push({ stage: "approved", level: "info", at: s.lzApproved, message: "Web user approved landing zone 1" });
    }

    const versions = [];
    let latestDone = 0;
    for (const [i, start] of s.started.entries()) {
      const n = i + 1;
      const saved = b.versions.find((x) => x.version === n);
      const { v, progress, done, end } = versionAt(saved, s.plans[i], now);
      v.created_at = iso(start);
      if (done) {
        v.finished_at = iso(end);
        latestDone = n;
        if (s.approved[n]) { v.approved_at = s.approved[n]; v.approved_by = "Web user"; }
      } else busy(v.stage, progress);
      versions.push(v);
      log = log.concat(versionLog(b, n, s.plans[i], start, now));
      if (s.approved[n]) log.push({ stage: "approved", level: "info", version: n, at: s.approved[n], message: `Web user approved version ${n}` });
    }
    run.latest_complete_version = latestDone || null;

    const iac = [];
    if (s.iac) {
      const step = stepAt({ ...b.iac[0].item, version: s.iacVersion }, s.iac, now, s.iacApproved);
      iac.push(step.item);
      log = log.concat(stepLog(b.iac[0].log, s.iac, now));
      if (!step.done) busy("iac", 20);
    }
    log.sort((x, y) => x.at.localeCompare(y.at));
    const current = versions.filter((v) => v.finished_at);
    const awaiting = run.status === "running" ? null : !s.lzApproved && lz.done ? "lz_approval"
      : current.length && !current.some((v) => v.approved_at) ? "adr_approval" : null;
    return { run, lz_versions: [lz.item], versions, iac, landing_zones: iac, awaiting, log };
  }

  function startVersion(s) {
    const at = Date.now();
    s.started.push(at);
    s.plans.push(schedule(at));
  }

  async function handle(method, path, body) {
    if (!path.startsWith(`/runs/${RUN_ID}`) && !(method === "GET" && path === "/runs")) return undefined;
    if (path === "/runs") return null; // the caller merges summary() into the real list
    const b = await load();
    const rest = path.slice(`/runs/${RUN_ID}`.length);
    if (method === "GET" && rest === "") return runState();
    const file = rest.match(/^\/files\/([^?]+)\?(.*)$/);
    if (method === "GET" && file) {
      const name = decodeURIComponent(file[1]);
      const q = Object.fromEntries(new URLSearchParams(file[2]));
      const f = q.iac ? (s0().iacVersion === Number(q.version) ? b.iac[0].files[name] : null)
        : q.lz ? b.lz[0].files[name] : (b.files[q.version] || {})[name];
      if (!f) fail(404, "file not found");
      return f;
    }
    const st = await runState();
    const s = readState();
    if (method === "POST" && st.run.status === "running") fail(409, "This run is still working. Wait until it finishes.");
    if (method === "POST" && rest === "/lz/approve") {
      if (Number(body && body.lz) !== 1 || !st.run.latest_complete_lz) fail(409, "Only a finished landing zone can be approved.");
      const first = !s.lzApproved;
      s.lzApproved = s.lzApproved || new Date().toISOString();
      if (first) startVersion(s);
      writeState(s);
      return { run_id: RUN_ID, lz: 1, approved_at: s.lzApproved, adr_started: first };
    }
    if (method === "POST" && (rest === "/lz/revise" || rest === "/lz")) {
      fail(409, "the sample run has no further landing zones; start a new run to revise one");
    }
    if (method === "POST" && rest === "/revise") {
      if (!s.lzApproved) fail(409, "Approve the landing zone first: the design starts after the landing-zone approval.");
      const next = st.versions.length + 1;
      if (!b.versions.find((x) => x.version === next)) fail(409, "the sample run has no further versions; start a new run to revise a design");
      startVersion(s);
      writeState(s);
      return { run_id: RUN_ID, version: next };
    }
    if (method === "POST" && rest === "/approve") {
      const n = Number(body && body.version);
      const v = st.versions.find((x) => x.version === n);
      if (!v || !v.finished_at) fail(409, "Only a finished version can be approved.");
      s.approved[n] = s.approved[n] || new Date().toISOString();
      const started = !s.iac;     // the recorded IaC (it depends only on the landing zone) plays for this version
      if (started) Object.assign(s, { iac: span(Date.now() + between(400, 800)), iacVersion: n });
      writeState(s);
      return { run_id: RUN_ID, version: n, approved_at: s.approved[n], iac_started: started };
    }
    if (method === "POST" && (rest === "/iac" || rest === "/iac/revise")) {
      fail(409, "the sample run has no further IaC; start a new run to revise one");
    }
    if (method === "POST" && rest === "/iac/approve") {
      const item = st.iac.find((x) => x.version === Number(body && body.version) && x.iac === Number(body && body.iac));
      if (!item || item.status !== "completed") fail(409, "Only finished IaC can be approved.");
      s.iacApproved = s.iacApproved || new Date().toISOString();
      writeState(s);
      return { run_id: RUN_ID, version: item.version, iac: item.iac, approved_at: s.iacApproved };
    }
    return fail(404, "not found");
  }

  async function summary() {
    if (!readState()) return null;
    const st = await runState();
    return { run_id: RUN_ID, title: st.run.title, status: st.run.status, created_at: st.run.created_at,
      version: st.versions.length, lz: 1, srs_filename: st.run.srs_filename };
  }

  return {
    id: RUN_ID,
    handle,
    summary,
    async begin() {
      const b = await load();
      writeState({ lz: span(Date.now() + between(400, 800)), started: [], plans: [], approved: {} });
      return b;
    },
    async srs() { const b = await load(); return { title: b.run.title, text: b.srs_text }; },
    async suggested(version) { const b = await load(); return (b.decisions || {})[String(version)] || null; },
  };
}

export const sampleRun = makeSampleRun();
