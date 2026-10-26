// Landing Zone Agent UI. Static SPA: Cognito Hosted UI (authorization code + PKCE) and the platform API.
// config.json is written by scripts/deploy.sh. No build step, no framework. Routes: #/dashboard, #/runs, #/run/<id>.
"use strict";

let cfg, token = null, claims = {};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const S = { runs: [], runId: "", data: null, tab: "organization", steps: false, file: null, timer: null };

/* ---------- auth ---------- */
const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
async function pkce() {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  return { verifier, challenge };
}
const redirectUri = () => location.origin + "/";
const decodeJwt = (t) => { try { return JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))); } catch { return {}; } };
const jwtExpired = (t) => { const c = decodeJwt(t); return !c.exp || c.exp * 1000 < Date.now() + 30000; };

async function login() {
  const { verifier, challenge } = await pkce();
  sessionStorage.setItem("pkce", verifier);
  const q = new URLSearchParams({ response_type: "code", client_id: cfg.clientId, redirect_uri: redirectUri(), scope: "openid email", code_challenge_method: "S256", code_challenge: challenge });
  location.href = `https://${cfg.cognitoDomain}/oauth2/authorize?${q}`;
}
async function exchange(code) {
  const body = new URLSearchParams({ grant_type: "authorization_code", client_id: cfg.clientId, code, redirect_uri: redirectUri(), code_verifier: sessionStorage.getItem("pkce") });
  const r = await fetch(`https://${cfg.cognitoDomain}/oauth2/token`, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body });
  if (!r.ok) throw new Error("login failed");
  const t = await r.json();
  sessionStorage.setItem("idToken", t.id_token);
  history.replaceState({}, "", "/");
  return t.id_token;
}
function logout() {
  sessionStorage.clear();
  location.href = `https://${cfg.cognitoDomain}/logout?client_id=${cfg.clientId}&logout_uri=${encodeURIComponent(redirectUri())}`;
}
function showGate(message) {
  clearTimeout(S.timer);
  $("app").hidden = true; $("gate").hidden = false;
  const n = $("gateNotice"); n.hidden = !message; n.textContent = message || "";
  $("login").onclick = login;
}
// The id token lasts 60 minutes. An expired one means signed out, not a wall of failing requests.
function expireSession() {
  sessionStorage.removeItem("idToken"); token = null;
  showGate("Your session expired. Sign in again to continue.");
  throw new Error("session expired");
}
async function api(path, opts = {}) {
  if (!token || jwtExpired(token)) expireSession();
  const r = await fetch(cfg.apiUrl + path, { ...opts, headers: { authorization: token, "content-type": "application/json" } });
  if (r.status === 401) expireSession();
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

/* ---------- helpers ---------- */
const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
const pretty = (id) => String(id || "").split("-").filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
const when = (ts) => new Date(ts * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
function ago(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
let toastTimer;
function toast(msg, kind = "") {
  const t = $("toast"); t.textContent = msg; t.className = kind; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), kind === "bad" ? 6000 : 2600);
}
const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;
const badge = (cls, text) => `<span class="badge badge-${cls}">${esc(text)}</span>`;
const basisBadge = (b) => ({ explicit: badge("blue", "Quoted from the SOW"), inferred: badge("muted", "Inferred"), default: badge("amber", "Default, not in the SOW") }[b] || "");
const kpi = (label, value, hint = "", tone = "") => `<div class="kpi ${tone ? "kpi-" + tone : ""}"><div class="kpi-label">${esc(label)}</div><div class="kpi-value">${esc(value)}</div>${hint ? `<div class="kpi-hint">${esc(hint)}</div>` : ""}</div>`;
const isDone = (run) => run.status === "DELIVERED" || run.status === "FAILED";

function stopRunButton(run) {
  if (run.status !== "RUNNING") return "";
  return `<button class="btn btn-sm" type="button" data-stop-run="${esc(run.runId)}" title="Stop Step Functions and mark this run failed">Stop run</button>`;
}
const isDeployRun = (run) => run.runKind === "deploy";
const STATE = {
  DELIVERED: ["green", "Ready to download"],
  FAILED: ["red", "Failed"],
  RUNNING: ["amber", "In progress"],
  AWAITING_INPUT: ["blue", "Starting"],
};
const stateBadge = (run) => {
  const [c, t] = STATE[run.status] || ["muted", run.status];
  return badge(c, t);
};
const runTypeBadge = (run) => (isDeployRun(run) ? badge("violet", "Deploy") : badge("muted", "Design"));
const runName = (r) => pretty(r.customerId);
const parseAuditDetail = (a) => {
  try {
    return typeof a.detail === "string" ? JSON.parse(a.detail || "{}") : a.detail || {};
  } catch {
    return {};
  }
};

function layout(nav, crumb, html) {
  ["dashboard", "runs"].forEach((n) => $("nav-" + n).classList.toggle("active", n === nav));
  $("crumb").textContent = crumb;
  document.title = `${crumb} · Landing Zone Agent`;
  $("view").innerHTML = html;
}

/* ---------- data ---------- */
async function loadRuns() { S.runs = (await api("/runs")).runs; return S.runs; }
const reportCache = new Map();  // report sha -> report
async function loadReport(id, run) {
  const a = run.artifacts && run.artifacts.report;
  if (!a) return null;
  if (!reportCache.has(a.sha)) {
    try { reportCache.set(a.sha, (await api(`/runs/${id}/artifacts/report?summary=1`)).report); } catch { return null; }
  }
  return reportCache.get(a.sha);
}
async function loadDeploymentReport(id, run) {
  const a = run.artifacts && run.artifacts["deployment-report"];
  if (!a) return null;
  const key = `dep:${a.sha}`;
  if (!reportCache.has(key)) {
    try {
      reportCache.set(key, (await api(`/runs/${id}/artifacts/deployment-report`)).deploymentReport);
    } catch {
      return null;
    }
  }
  return reportCache.get(key);
}

/* ---------- dashboard ---------- */
function runsTable(runs, { limit } = {}) {
  const rows = limit ? runs.slice(0, limit) : runs;
  if (!rows.length) return '<div class="empty">No runs yet. Upload a SOW above to start one.</div>';
  return `<div class="tbl-wrap"><table><thead><tr><th>Customer</th><th>Type</th><th>Started</th><th>State</th><th>Run</th><th></th></tr></thead><tbody>${rows.map((r) => `
    <tr class="click" data-open="${esc(r.runId)}"><td class="name">${esc(runName(r))}${isDeployRun(r) && r.designRunId ? `<div class="hint">from design <code>${esc(r.designRunId.slice(0, 8))}</code></div>` : ""}</td><td>${runTypeBadge(r)}</td><td>${esc(ago(r.createdAt))}</td><td>${stateBadge(r)}</td><td><code>${esc(r.runId.slice(0, 8))}</code></td>
    <td>${r.status === "FAILED" && r.error ? `<span style="color:var(--red)">${esc(r.error.length > 90 ? r.error.slice(0, 90) + "…" : r.error)}</span>` : `<a href="#/run/${esc(r.runId)}">View →</a>`}</td></tr>`).join("")}</tbody></table></div>`;
}

function viewDashboard() {
  S.runId = ""; S.data = null; clearTimeout(S.timer);
  const now = Date.now() / 1000, recent = S.runs.filter((r) => now - r.createdAt < 30 * 86400);
  const del = recent.filter((r) => r.status === "DELIVERED").length, bad = recent.filter((r) => r.status === "FAILED").length, run = recent.filter((r) => !isDone(r)).length;
  const rate = del + bad ? `${((del / (del + bad)) * 100).toFixed(1)}%` : "–";
  layout("dashboard", "Dashboard", `
    <div class="page-title">Landing Zone</div>
    <p class="page-sub">Turn a customer's statement of work into landing zone code. The agent reads the whole SOW, draws the AWS organization it describes, and generates Terraform and CloudFormation with a security scan attached.</p>
    <div class="grid-kpi">${kpi("Runs (30 days)", recent.length, `${del} delivered · ${bad} failed`)}${kpi("Success rate", rate, "of finished runs", del + bad ? "green" : "")}
      ${kpi("In progress", run, run ? "Generating now" : "Nothing running", run ? "amber" : "")}${kpi("Failed", bad, bad ? "Open a run to see why" : "No failures", bad ? "red" : "")}</div>
    <div class="two">
      <form class="card" id="newForm" novalidate>
        <div class="card-head"><h2>New run</h2><span class="card-aside">Takes a few minutes</span></div>
        <label class="drop" id="drop"><span class="big">⇪</span><strong>Drop the SOW here, or browse</strong><span class="hint">PDF, DOCX, TXT or Markdown, up to 10 MB</span><input type="file" id="file" accept=".pdf,.docx,.txt,.md"></label>
        <div class="field"><label class="lbl" for="customer">Customer name</label><input class="input" type="text" id="customer" placeholder="Moon Trades" autocomplete="off" maxlength="60"><div class="hint" id="customerHint">Names the run and the generated files.</div></div>
        <details class="field"><summary>Add requirements that aren't in the file</summary><textarea class="textarea" id="req" placeholder="Anything the customer asked for outside the document." style="margin-top:8px"></textarea></details>
        <p class="errtext" id="formError" role="alert" hidden></p>
        <button class="btn btn-primary btn-lg" id="create" type="submit">▶ Generate landing zone code</button>
      </form>
      <div class="card">
        <div class="card-head"><h2>What you get</h2></div>
        <ul class="items">
          <li class="block"><span class="main">The organization it understood</span><div class="meta">A tree of OUs and accounts drawn from the SOW, so you can check it before anything is built.</div></li>
          <li class="block"><span class="main">Terraform and CloudFormation</span><div class="meta">The same landing zone in both, validated before you can download them.</div></li>
          <li class="block"><span class="main">Custom SCPs for review</span><div class="meta">Policies the catalog can't express, written from the SOW and delivered for a person to check.</div></li>
          <li class="block"><span class="main">Scan evidence</span><div class="meta">How many security checks ran, passed and failed, bundled with the code.</div></li>
        </ul>
        <p class="hint" style="margin-top:10px">Design runs produce code only. After validation, you can start an optional <strong>Deploy</strong> run (AWS Transform) from the run detail page.</p>
      </div>
    </div>
    <div class="card" style="margin-top:14px"><div class="card-head"><h2>Recent runs</h2><a class="card-aside" href="#/runs">All runs →</a></div>${runsTable(S.runs, { limit: 5 })}</div>`);
  S.file = null;
  const drop = $("drop"), input = $("file");
  input.onchange = () => { S.file = input.files[0] || null; paintFile(); };
  ["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (ev) => { const f = ev.dataTransfer.files[0]; if (f) { input.value = ""; S.file = f; paintFile(); } });
  $("customer").oninput = () => { const s = slug($("customer").value); $("customerHint").textContent = s ? `Run name: ${s}` : "Names the run and the generated files."; };
  $("newForm").onsubmit = (e) => { e.preventDefault(); createRun(); };
}
function paintFile() {
  const box = $("drop");
  let p = $("picked");
  if (!S.file) { box.hidden = false; if (p) p.remove(); return; }
  box.hidden = true;
  if (!p) { p = document.createElement("div"); p.id = "picked"; p.className = "picked"; box.after(p); }
  p.innerHTML = `<div><div class="name">${esc(S.file.name)}</div><div class="hint">${(S.file.size / 1024 / 1024).toFixed(2)} MB</div></div><button class="btn btn-sm" type="button" id="clearFile">Remove</button>`;
  $("clearFile").onclick = () => { S.file = null; $("file").value = ""; paintFile(); };
}
function formError(msg) { const e = $("formError"); e.hidden = !msg; e.textContent = msg || ""; }

async function createRun() {
  formError("");
  const f = S.file, id = slug($("customer").value), req = $("req").value.trim();
  if (id.length < 3) return formError("Enter the customer's name (at least 3 letters or numbers).");
  if (!f && !req) return formError("Add the SOW file, or type the requirements.");
  if (f && !/\.(pdf|docx|txt|md)$/i.test(f.name)) return formError("This file type isn't supported. Use PDF, DOCX, TXT or Markdown.");
  if (f && f.size > 10 * 1024 * 1024) return formError("This file is larger than 10 MB. Split it or upload the relevant sections.");
  const btn = $("create"); btn.disabled = true;
  try {
    btn.textContent = "Preparing...";
    const { runId, upload } = await api("/runs", { method: "POST", body: JSON.stringify({ customerId: id, requirements: req, fileName: f ? f.name : "" }) });
    if (upload) {
      btn.textContent = "Uploading the SOW...";
      const fd = new FormData();
      Object.entries(upload.fields).forEach(([k, v]) => fd.append(k, v));
      fd.append("file", f);
      const up = await fetch(upload.url, { method: "POST", body: fd });
      if (!up.ok) throw new Error(`The upload failed (${up.status}). Try again.`);
    }
    btn.textContent = "Starting...";
    await api(`/runs/${runId}/start`, { method: "POST" });
    await loadRuns().catch(() => {});
    location.hash = `#/run/${runId}`;
  } catch (e) {
    if (e.message !== "session expired") { formError(e.message); btn.disabled = false; btn.textContent = "▶ Generate landing zone code"; }
  }
}

/* ---------- runs ---------- */
function viewRuns() {
  S.runId = ""; S.data = null; clearTimeout(S.timer);
  layout("runs", "Runs", `<div class="page-title">Run history</div>
    <p class="page-sub">Design runs generate IaC from a SOW; deploy runs apply Transform in your org and produce a foundation attestation. Open any run for progress, downloads, and activity.</p>
    <div class="panel panel-pad">${runsTable(S.runs)}</div>`);
}

/* ---------- run detail ---------- */
async function openRun(id, { silent = false } = {}) {
  S.runId = id;
  try {
    const { run } = await api(`/runs/${id}`);
    const { audit } = await api(`/runs/${id}/audit`);
    let scope = null, diagram = "";
    if (isDeployRun(run) && run.designRunId) {
      try {
        const design = (await api(`/runs/${run.designRunId}`)).run;
        if (design.artifacts && design.artifacts.intake) {
          const r = await api(`/runs/${run.designRunId}/scope`);
          scope = r.scope;
          diagram = r.orgDiagram || "";
        }
      } catch { /* design scope optional while loading */ }
    } else if (run.artifacts && run.artifacts.intake) {
      try { const r = await api(`/runs/${id}/scope`); scope = r.scope; diagram = r.orgDiagram || ""; } catch { /* still being written */ }
    }
    const report = isDeployRun(run) ? null : await loadReport(id, run);
    const deploymentReport = isDeployRun(run) ? await loadDeploymentReport(id, run) : null;
    if (S.runId !== id) return;  // the user moved on while this was loading
    const first = !S.data || S.data.run.runId !== id, hadScope = S.data && S.data.scope;
    S.data = { run, audit, scope, diagram, report, deploymentReport };
    if (first || (!hadScope && scope)) {
      if (isDeployRun(run)) S.tab = deploymentReport ? "deployment" : scope ? "organization" : "activity";
      else S.tab = scope ? "organization" : "activity";
    }
    renderRun();
    clearTimeout(S.timer);
    if (!isDone(run)) S.timer = setTimeout(() => openRun(id, { silent: true }), 4000);
    else loadRuns().catch(() => {});
  } catch (e) {
    if (e.message === "session expired") return;
    if (!silent) { toast(e.message === "not found" ? "That run isn't available to you." : e.message, "bad"); location.hash = "#/runs"; }
  }
}

function stepsHtml(run, audit) {
  const has = (a) => audit.some((x) => x.action === a);
  const done = [has("sow.extracted"), has("phase.completed"), has("bundle.rendered"), run.status === "DELIVERED"];
  const steps = [["Read the SOW", "Extract the text"], ["Understand the scope", "Map every requirement"], ["Generate the code", "Terraform and CloudFormation"], ["Validate and scan", "Lint and security scan"]];
  const next = done.indexOf(false), failed = run.status === "FAILED";
  return `<div class="steps">${steps.map(([name, sub], i) => {
    const state = done[i] ? "done" : i === next ? (failed ? "failed" : run.status === "AWAITING_INPUT" ? "" : "active") : "";
    return `<div class="step ${state}"><div class="step-rail"><span class="step-node"></span><span class="step-line"></span></div>
      <div class="step-body"><div class="step-name">${esc(name)}</div><div class="step-sub">${esc(done[i] ? "Done" : state === "failed" ? "Stopped here" : state === "active" ? "In progress" : sub)}</div></div>
      <span class="step-check">${done[i] ? "✓" : state === "failed" ? "✕" : ""}</span></div>`;
  }).join("")}</div>`;
}

function renderRun() {
  if (isDeployRun(S.data.run)) return renderDeployRun();
  const { run, audit, scope, diagram, report } = S.data;
  const name = scope ? scope.customer.orgName : runName(run);
  const tabs = [];
  if (scope && diagram) tabs.push(["organization", "Organization"]);
  if (scope) tabs.push(["scope", "Scope"], ["scps", "Custom SCPs", (scope.customScps || []).length]);
  if (report) tabs.push(["security", "Security and validation"]);
  tabs.push(["activity", "Activity"]);
  if (!tabs.some((t) => t[0] === S.tab)) S.tab = tabs[0][0];
  const s = scope && scope.summary;
  const kpis = s ? `<div class="grid-kpi">${kpi("OUs", s.ous)}${kpi("Accounts", s.accounts)}${kpi("Controls enabled", s.controlAttachments)}${kpi("Catalog SCPs", s.scps)}${kpi("Custom SCPs", s.customScps || 0, "for review", s.customScps ? "amber" : "")}</div>` : "";
  const failure = run.status === "FAILED" ? `<div class="notice notice-err" role="alert"><strong>This run failed.</strong> ${esc(run.error || "No reason was recorded.")}<br>A failed run can't be resumed. <a href="#/dashboard">Start a new run</a>, or open the Activity tab to see where it stopped.</div>` : "";
  const body = !scope && !isDone(run)
    ? `<div class="card"><div class="card-head"><h2><span class="spin"></span> The agent is reading the SOW</h2></div><p class="meta" style="color:var(--dim)">This usually takes a few minutes. You can leave this page: the run continues and stays under Runs.</p></div>`
    : `<div class="panel panel-pad"><div class="tabs" role="tablist" aria-label="Run details">${tabs.map(([id, label, n]) =>
        `<button class="tab" role="tab" id="tab-${id}" aria-selected="${S.tab === id}" aria-controls="panel-${id}" data-tab="${id}" tabindex="${S.tab === id ? 0 : -1}">${esc(label)}${n ? `<span class="count">${n}</span>` : ""}</button>`).join("")}</div>
      <div role="tabpanel" id="panel-${S.tab}" aria-labelledby="tab-${S.tab}">${panel(S.tab)}</div></div>`;
  layout("runs", name, `<div class="crumbs"><a href="#/runs">← Runs</a></div>
    <div class="page-title" style="display:flex;flex-wrap:wrap;align-items:center;gap:10px">${esc(name)} ${runTypeBadge(run)} ${stateBadge(run)} ${stopRunButton(run)}</div>
    <p class="page-sub" style="margin-bottom:18px">Started ${esc(when(run.createdAt))} · Design run <code>${esc(run.runId.slice(0, 8))}</code></p>
    ${failure}
    <div class="grid-3"><div class="card"><div class="card-head"><h2>Progress</h2></div>${stepsHtml(run, audit)}</div>${deliverables(run)}<div>${deployCtaCard(run)}${inputs(scope)}</div></div>
    ${kpis}${body}`);
  if (S.tab === "organization" && diagram) drawDiagram(diagram);
}

function deployCtaCard(run) {
  if (isDeployRun(run) || run.status !== "DELIVERED") return "";
  return `<div class="card"><div class="card-head"><h2>Deploy</h2></div>
    <p class="hint">Run the deploy agent against a target AWS account (cross-account role or keys). Organizations discover and attestation use that account; Transform jobs use the platform workspace.</p>
    <button class="btn btn-primary" type="button" data-deploy="${esc(run.runId)}">Start deploy run</button></div>`;
}

function deployStepsHtml(run, audit) {
  const has = (a) => audit.some((x) => x.action === a);
  const hasTool = (name) => audit.some((x) => x.action === name);
  const done = [
    hasTool("tool.run_pre_discover") || hasTool("tool.run_pre_discover.failed"),
    hasTool("tool.save_iac_change_plan") || hasTool("tool.render_iac_bundles"),
    hasTool("tool.transform_start_deploy"),
    has("deploy.attested") || (run.status === "DELIVERED" && has("phase.completed")),
  ];
  const steps = [
    ["Discover baseline", "Organizations snapshot and gap analysis"],
    ["Analyze and plan", "Transform analyze, assessment, and IaC plan"],
    ["Transform deploy", "Apply changes in the target org"],
    ["Attest and deliver", "Foundation report and artifacts"],
  ];
  const next = done.indexOf(false), failed = run.status === "FAILED";
  return `<div class="steps">${steps.map(([name, sub], i) => {
    const state = done[i] ? "done" : i === next ? (failed ? "failed" : run.status === "AWAITING_INPUT" ? "" : "active") : "";
    return `<div class="step ${state}"><div class="step-rail"><span class="step-node"></span><span class="step-line"></span></div>
      <div class="step-body"><div class="step-name">${esc(name)}</div><div class="step-sub">${esc(done[i] ? "Done" : state === "failed" ? "Stopped here" : state === "active" ? "In progress" : sub)}</div></div>
      <span class="step-check">${done[i] ? "✓" : state === "failed" ? "✕" : ""}</span></div>`;
  }).join("")}</div>`;
}

function deployContinueNotice(audit, run) {
  const lastCont = [...audit].reverse().find((a) => a.action === "phase.continue");
  const lastYield = [...audit].reverse().find((a) => a.action === "tool.yield_for_orchestrator");
  const d = lastCont ? parseAuditDetail(lastCont) : {};
  const reason = String(d.reason || (lastYield ? parseAuditDetail(lastYield).reason : "") || "").trim();
  if (!lastCont && !reason) return "";
  const targetAcct = run && run.deployTarget && run.deployTarget.accountId;
  if (/^Pre-discover failed for deploy target account/i.test(reason)) {
    return `<div class="notice notice-warn" role="status"><strong>Deploy paused (target discover).</strong> ${esc(reason.length > 480 ? reason.slice(0, 480) + "…" : reason)}<br><span class="hint">Fix the issue in account ${esc(targetAcct || "556")}, then start a new deploy run.</span></div>`;
  }
  const wrong831OrgAdvice =
    targetAcct &&
    targetAcct !== "831493647146" &&
    /831493647146.*(create|enable).*org|create-organization.*831|Organizations not yet created.*831493647146|management account 831493647146/i.test(reason);
  const platformBlock =
    !wrong831OrgAdvice &&
    /permission|IAM|AccessDenied|not authorized|s3:|organization|create-organization|831493647146|platform account|run_pre_discover|NotInUse/i.test(
      reason
    );
  if (d.awaitingHitl && !platformBlock && !wrong831OrgAdvice) {
    return `<div class="notice notice-info" role="status"><strong>Waiting on AWS Transform.</strong> Complete the required step in the Transform workspace. The deploy agent will resume on its own.</div>`;
  }
  if (wrong831OrgAdvice) {
    return `<div class="notice notice-warn" role="status"><strong>Deploy paused — ignore “create org in 831”.</strong> This run targets account <code>${esc(targetAcct)}</code>. The agent skipped discover and gave incorrect platform advice. Use valid <strong>${esc(targetAcct)}</strong> credentials (or AssumeRole), add AgentRole as Contributor+ on the Transform workspace in 831, then start a <strong>new</strong> deploy run after redeploying the latest agent.<br><span class="hint">Step Functions may keep retrying this run until you stop it.</span></div>`;
  }
  if (reason) {
    const cls = platformBlock ? "notice-warn" : "notice-info";
    const lead = platformBlock
      ? "<strong>Deploy paused (platform setup).</strong>"
      : "<strong>Deploy paused.</strong>";
    return `<div class="notice ${cls}" role="status">${lead} ${esc(reason.length > 420 ? reason.slice(0, 420) + "…" : reason)}<br><span class="hint">Step Functions will retry until you use <strong>Stop run</strong> or the run fails.</span></div>`;
  }
  return "";
}

function renderDeployRun() {
  const { run, audit, scope, diagram, deploymentReport } = S.data;
  const name = scope ? scope.customer.orgName : runName(run);
  const tabs = [];
  if (deploymentReport) tabs.push(["deployment", "Deployment report"]);
  if (scope && diagram) tabs.push(["organization", "Organization"]);
  if (scope) tabs.push(["scope", "Scope"]);
  tabs.push(["activity", "Activity"]);
  if (!tabs.length) tabs.push(["activity", "Activity"]);
  if (!tabs.some((t) => t[0] === S.tab)) S.tab = tabs[0][0];
  const designLink = run.designRunId
    ? ` · Design run <a href="#/run/${esc(run.designRunId)}"><code>${esc(run.designRunId.slice(0, 8))}</code></a>`
    : "";
  const failure = run.status === "FAILED"
    ? `<div class="notice notice-err" role="alert"><strong>Deploy failed.</strong> ${esc(run.error || "No reason was recorded.")}<br>Open the Activity tab or deployment report for details.</div>`
    : "";
  const waiting = !isDone(run)
    ? `<div class="card"><div class="card-head"><h2><span class="spin"></span> Deploy agent running</h2></div><p class="meta" style="color:var(--dim)">Transform and discovery can take a while. This page refreshes every few seconds. You can leave and come back from Runs.</p></div>`
    : "";
  const body = isDone(run) || scope
    ? `<div class="panel panel-pad"><div class="tabs" role="tablist" aria-label="Deploy run details">${tabs.map(([id, label, n]) =>
        `<button class="tab" role="tab" id="tab-${id}" aria-selected="${S.tab === id}" aria-controls="panel-${id}" data-tab="${id}" tabindex="${S.tab === id ? 0 : -1}">${esc(label)}${n ? `<span class="count">${n}</span>` : ""}</button>`).join("")}</div>
      <div role="tabpanel" id="panel-${S.tab}" aria-labelledby="tab-${S.tab}">${panel(S.tab)}</div></div>`
    : waiting;
  layout("runs", `${name} deploy`, `<div class="crumbs"><a href="#/runs">← Runs</a></div>
    <div class="page-title" style="display:flex;flex-wrap:wrap;align-items:center;gap:10px">${esc(name)} ${runTypeBadge(run)} ${stateBadge(run)} ${stopRunButton(run)}</div>
    <p class="page-sub" style="margin-bottom:18px">Started ${esc(when(run.createdAt))} · Deploy run <code>${esc(run.runId.slice(0, 8))}</code>${designLink}</p>
    ${failure}${deployContinueNotice(audit, run)}
    <div class="grid-3"><div class="card"><div class="card-head"><h2>Progress</h2></div>${deployStepsHtml(run, audit)}</div>${deployDeliverables(run)}</div>
    ${body}`);
  if (S.tab === "organization" && diagram) drawDiagram(diagram);
}

function deployDeliverables(run) {
  const ok = run.status === "DELIVERED";
  const has = (k) => run.artifacts && run.artifacts[k];
  const b = (k, label, primary) => `<button class="btn ${primary ? "btn-primary" : ""}" type="button" data-dl="${k}" ${ok && has(k) ? "" : "disabled"}>⤓ ${label}</button>`;
  const note = ok
    ? "Foundation attestation, IaC plan, manifest, and evidence JSON from the deploy workflow."
    : run.status === "FAILED"
      ? "Deliverables appear here if attestation completed before failure."
      : "Available when the deploy run finishes successfully.";
  return `<div class="card"><div class="card-head"><h2>Deliverables</h2></div><div style="display:flex;gap:8px;flex-wrap:wrap">${b("deployment-report", "Deployment report", true)}${b("foundation-assessment", "Foundation assessment")}${b("iac-change-plan", "IaC change plan")}${b("iac-manifest", "IaC manifest")}</div><p class="hint" style="margin-top:10px">${note}</p></div>`;
}

function deliverables(run) {
  const ok = run.status === "DELIVERED", has = (k) => run.artifacts && run.artifacts[k];
  const b = (k, label, primary) => `<button class="btn ${primary ? "btn-primary" : ""}" type="button" data-dl="${k}" ${(k === "reports" ? has("reports") : ok) ? "" : "disabled"}>⤓ ${label}</button>`;
  const note = ok ? "Each zip includes the docs, the custom SCPs for review, and its own scan reports."
    : run.status === "FAILED" ? (has("reports") ? "The code isn't available because validation failed. The scan reports are." : "The code isn't available because the run failed.")
    : "Ready when validation finishes.";
  return `<div class="card"><div class="card-head"><h2>Deliverables</h2></div><div style="display:flex;gap:8px;flex-wrap:wrap">${b("terraform", "Terraform", true)}${b("cloudformation", "CloudFormation")}${b("reports", "Scan reports")}</div><p class="hint" style="margin-top:10px">${note}</p></div>`;
}
function inputs(scope) {
  if (!scope) return "";
  const need = scope.missingRequired || [], q = (scope.openQuestions || []).length;
  if (!need.length && !q) return "";
  return `<div class="card"><div class="card-head"><h2>Before you apply</h2></div>
    ${need.length ? `<ul class="todo">${need.map((n) => `<li><b>!</b><span>${esc(n[0].toUpperCase() + n.slice(1))}</span></li>`).join("")}</ul>
      <p class="hint" style="margin-top:10px">Each account needs a unique root email that has never been used for another AWS account. Terraform reads them from <code>terraform.tfvars</code>, CloudFormation from the parameter files.</p>` : ""}
    ${q ? `<p style="margin-top:${need.length ? 10 : 0}px;font-size:13px">${plural(q, "open question")} to confirm with the customer. <button class="btn-link" type="button" data-tab="scope">Review</button></p>` : ""}</div>`;
}

/* ---------- tab panels ---------- */
function panel(tab) {
  const { scope, diagram, report, deploymentReport, audit } = S.data;
  if (tab === "deployment") return deploymentPanel(deploymentReport);
  if (tab === "organization") return orgPanel(diagram);
  if (tab === "scope") return scopePanel(scope);
  if (tab === "scps") return scpPanel(scope);
  if (tab === "security") return securityPanel(report);
  return activityPanel(audit);
}

const DEPLOY_OVERALL = {
  pass: ["green", "Foundation attestation passed"],
  pass_with_manual_steps: ["amber", "Passed with manual steps"],
  fail: ["red", "Attestation failed"],
};
function deploymentPanel(rep) {
  if (!rep) return '<div class="empty">The deployment report is not available yet.</div>';
  const [tone, label] = DEPLOY_OVERALL[rep.overall] || ["muted", rep.overall];
  const pre = rep.observed && rep.observed.preDeploy;
  const post = rep.observed && rep.observed.postDeploy;
  const gapList = (g) => {
    if (!g) return "None listed";
    const parts = [];
    if ((g.missingOus || []).length) parts.push(`${g.missingOus.length} missing OU(s)`);
    if ((g.missingAccountsByName || []).length) parts.push(`${g.missingAccountsByName.length} missing account name(s)`);
    return parts.length ? parts.join(", ") : "No missing OUs or account names vs scope";
  };
  const reasons = (rep.outcomeReasons || []).length
    ? `<ul class="bullets">${rep.outcomeReasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>`
    : "";
  const cls = rep.classification || {};
  return `<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:14px">${badge(tone, label)}
      <span class="hint">Design run <code>${esc((rep.designRunId || "").slice(0, 8))}</code></span></div>
    ${reasons}
    <div class="grid-kpi">${kpi("Pre-deploy OUs", pre ? pre.ouCount : "–")}${kpi("Post-deploy OUs", post ? post.ouCount : "–")}${kpi("Pre-deploy accounts", pre ? pre.accountCount : "–")}${kpi("Post-deploy accounts", post ? post.accountCount : "–")}</div>
    <section class="sec"><h3>Classification</h3><dl class="kv"><dt>Before deploy</dt><dd>${esc(cls.preDeploy || "–")}</dd><dt>After deploy</dt><dd>${esc(cls.postDeploy || "–")}</dd></dl></section>
    <section class="sec"><h3>Gaps vs approved scope</h3><dl class="kv"><dt>Pre-deploy</dt><dd>${esc(gapList(rep.gaps && rep.gaps.preDeploy))}</dd><dt>Post-deploy</dt><dd>${esc(gapList(rep.gaps && rep.gaps.postDeploy))}</dd></dl>
      <p class="hint">${esc(rep.disclaimer || "")}</p></section>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px"><button class="btn btn-primary" type="button" data-dl="deployment-report">⤓ Deployment report (JSON)</button></div>`;
}

const LEGEND = [["#0e1e33", "#2b8ef0", "Created by the stacks"], ["#1f1b3d", "#9b8cf7", "Security OU and shared accounts, set up by Control Tower"], ["#1a1f29", "#8b94a3", "Already exists"]];
const diagramCache = new Map();  // mermaid text -> svg
let mermaidReady = false;
function orgPanel(text) {
  return `<div class="legendrow"><div class="legend">${LEGEND.map(([bg, bd, t]) => `<span><i style="background:${bg};border-color:${bd}"></i>${esc(t)}</span>`).join("")}</div>
    <button class="btn btn-sm" type="button" data-full="1">⤢ View full screen</button></div>
    <div class="paper" id="orgdiagram">${diagramCache.get(text) || '<div class="paper-empty">Drawing the organization...</div>'}</div>
    <details style="margin-top:12px"><summary>Diagram source</summary><pre style="overflow:auto;margin-top:8px;color:var(--dim)"><code>${esc(text)}</code></pre></details>`;
}
async function drawDiagram(text) {
  const box = $("orgdiagram");
  if (!box || diagramCache.has(text)) return;
  try {
    if (typeof mermaid === "undefined") throw new Error("diagram library unavailable");
    if (!mermaidReady) {
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base", fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        themeVariables: { background: "transparent", lineColor: "#8b94a3", primaryColor: "#0e1e33", primaryTextColor: "#e6e9ef", primaryBorderColor: "#2b8ef0", textColor: "#e6e9ef", fontSize: "14px" },
        flowchart: { curve: "basis", padding: 14, htmlLabels: true } });
      mermaidReady = true;
    }
    const { svg: out } = await mermaid.render("orgsvg" + Date.now(), text);
    diagramCache.set(text, out);
    if ($("orgdiagram")) $("orgdiagram").innerHTML = out;
  } catch { box.innerHTML = '<div class="paper-empty">The diagram could not be drawn here. Its source is below, and it is also in docs/ORG-STRUCTURE.md in each download.</div>'; }
}

function limited(items, render, max, label) {
  if (items.length <= max) return `<ul class="items">${items.map(render).join("")}</ul>`;
  return `<ul class="items">${items.slice(0, max).map(render).join("")}</ul><details><summary style="padding:6px 0">Show all ${items.length} ${label}</summary><ul class="items">${items.slice(max).map(render).join("")}</ul></details>`;
}
function scopePanel(s) {
  const r = s.regions, lg = s.logging, created = "Created by the stacks from the email you provide";
  const sec = (title, sub, inner) => `<section class="sec"><h3>${title}${sub ? `<small>${sub}</small>` : ""}</h3>${inner}</section>`;
  return `<div>
    ${sec("Regions", "", `<dl class="kv"><dt>Home</dt><dd><code>${esc(r.home)}</code></dd><dt>Governed</dt><dd>${r.governed.map((x) => `<code>${esc(x)}</code>`).join(" ")}</dd>
      <dt>Also allowed</dt><dd>${r.extraAllowed.length ? r.extraAllowed.map((x) => `<code>${esc(x)}</code>`).join(" ") : "None"}</dd>
      <dt>Region deny</dt><dd>${r.enforceDeny ? `On: ${r.denied.length} regions denied (derived from the governed regions)` : "Off"}</dd></dl>
      <details style="margin-top:8px"><summary>Denied regions</summary><p class="hint" style="margin-top:6px">${esc(r.denied.join(", "))}</p></details>`)}
    ${sec("Logging", "", `<dl class="kv"><dt>Log retention</dt><dd>${lg.retentionDays} days</dd><dt>Access log retention</dt><dd>${lg.accessLogRetentionDays} days</dd>
      <dt>Log archive account</dt><dd>${esc(lg.logArchiveAccountId || created)}</dd><dt>Audit account</dt><dd>${esc(lg.auditAccountId || created)}</dd><dt>Encryption key</dt><dd>${esc(lg.kmsKeyArn || "Control Tower default")}</dd></dl>`)}
    ${sec("Organizational units", plural(s.ous.length, "unit"), limited(s.ous, (o) => `<li><span class="main">${esc(o.name)}</span>${o.parent ? `<span class="meta">inside ${esc(o.parent)}</span>` : ""}${basisBadge(o.basis)}</li>`, 8, "units"))}
    ${sec("Accounts", plural((s.accounts || []).length, "account"), limited(s.accounts || [], (a) => `<li><span class="main">${esc(a.name)}</span><span class="meta">${esc(a.kind)} in ${esc(a.ou)}${a.provisioning === "existing" ? ", already exists" : ""}</span>${basisBadge(a.basis)}</li>`, 8, "accounts"))}
    ${sec("Service control policies from the catalog", plural(s.scps.length, "policy", "policies"), s.scps.length ? limited(s.scps, (p) => `<li><code>${esc(p.id)}</code><span class="meta">on ${esc(p.targets.join(", "))}</span>${basisBadge(p.basis)}</li>`, 8, "policies") : '<p class="hint">None.</p>')}
    ${sec("Control Tower controls", `${s.summary.controls} controls, ${s.summary.controlAttachments} attachments`, limited(s.controls, (c) => `<li><code>${esc(c.id)}</code><span class="meta">on ${esc(c.targets.join(", "))}</span>${basisBadge(c.basis)}</li>`, 6, "controls"))}
    ${sec("Not covered by the generated code", plural(s.unsupported.length, "requirement"), s.unsupported.length ? limited(s.unsupported, (u) => `<li class="block"><span class="main">${esc(u.requirement)}</span><div class="meta">${esc(u.reason)}</div></li>`, 5, "requirements") : '<p class="hint">Every requirement is covered.</p>')}
    ${sec("Assumptions", "", s.assumptions.length ? `<ul class="bullets">${s.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : '<p class="hint">None.</p>')}
    ${sec("Open questions", "to confirm with the customer", s.openQuestions.length ? `<ul class="bullets">${s.openQuestions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : '<p class="hint">None.</p>')}
  </div>`;
}

function scpPanel(s) {
  const list = s.customScps || [];
  const note = `<div class="notice notice-info"><strong>Written by an AI model from the SOW.</strong> Review each policy against its quote, fill in its inputs, and test it on a non-production account first. The generated code never applies them: they ship in <code>custom-scps/</code>.</div>`;
  if (!list.length) return note + '<div class="empty">This SOW has no requirements that need a custom policy beyond the catalog.</div>';
  return note + list.map((e, i) => `<div class="card scp"><div class="top"><div><h4>${esc(e.title)}</h4><div class="desc">${esc(e.description || "")}</div></div>
      <button class="btn btn-sm" type="button" data-copy="${i}">⧉ Copy policy</button></div>
    <div class="row"><code>${esc(e.id)}</code><span>attach to</span>${e.targets.map((t) => badge("blue", t)).join("")}${basisBadge(e.basis)}</div>
    ${e.inputs.length ? `<div class="row"><span>Fill in before use</span>${e.inputs.map((x) => `<span class="badge badge-amber" title="${esc(x.description)}">${esc(x.name)}</span>`).join("")}</div>` : ""}
    ${e.warnings.length ? `<div class="notice notice-warn" style="margin:10px 0 0">${e.warnings.map(esc).join(" ")}</div>` : ""}
    <details style="margin-top:10px"><summary>Policy JSON <span class="hint">${esc(plural((e.policy.Statement || []).length, "statement"))}</span></summary><pre><code>${esc(JSON.stringify(e.policy, null, 2))}</code></pre></details></div>`).join("");
}

const CHECKS = { "tf-fmt": "Terraform format", "tf-init": "Terraform init", "tf-validate": "Terraform validate", "tf-lint": "Terraform lint", "tf-security": "Terraform security scan", "cfn-lint": "CloudFormation lint", "cfn-security": "CloudFormation security scan" };
function securityPanel(rep) {
  const t = rep.security.totals;
  const bar = (label, s) => {
    if (!s) return `<div class="barrow"><div class="lab">${label}<span>The scan produced no report</span></div></div>`;
    const n = s.passed + s.failed + s.skipped, pc = (x) => `${n ? (x / n) * 100 : 0}%`;
    return `<div class="barrow"><div class="lab">${label}<span>${n} checks: ${s.passed} passed, ${s.failed} failed${s.skipped ? `, ${s.skipped} skipped` : ""}</span></div>
      <div class="pbar" role="img" aria-label="${s.passed} passed, ${s.failed} failed"><i class="g" style="width:${pc(s.passed)}"></i><i class="r" style="width:${pc(s.failed)}"></i><i class="k" style="width:${pc(s.skipped)}"></i></div></div>`;
  };
  const failed = ["terraform", "cloudformation"].flatMap((f) => ((rep.security[f] || {}).failedChecks || []).map((c) => ({ ...c, stack: f })));
  return `<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:14px">${badge(rep.overall === "pass" ? "green" : "red", rep.overall === "pass" ? "All validation checks passed" : "Validation failed")}
      <span class="hint">Scanned ${esc(when(Date.parse(rep.generatedAt) / 1000))}</span></div>
    <div class="grid-kpi">${kpi("Checks scanned", t.scanned)}${kpi("Passed", t.passed, "", "green")}${kpi("Failed", t.failed, t.failed ? "Listed below" : "None", t.failed ? "red" : "")}${kpi("Skipped", t.skipped)}</div>
    <section class="sec"><h3>Security scan <small>checkov</small></h3>${bar("Terraform", rep.security.terraform)}${bar("CloudFormation", rep.security.cloudformation)}
      <p class="hint">The security scan looks for risky configuration in the generated code. Findings are reported here and in the downloads but do not block delivery.</p>
      ${failed.length ? `<ul class="failures">${failed.map((c) => `<li><b>${esc(c.id)}</b> ${esc(c.name)}<small>${esc(c.stack)}: ${esc(c.resource)}, ${esc(c.file)}</small></li>`).join("")}</ul>` : ""}</section>
    <section class="sec"><h3>Validation <small>does the code work and follow best practice</small></h3>
      <ul class="checks">${rep.checks.map((c) => `<li><span class="${c.result === "pass" ? "ok" : "no"}">${c.result === "pass" ? "✓" : "✕"}</span>${esc(CHECKS[c.name] || c.name)}</li>`).join("")}</ul>
      <p class="hint" style="margin-top:8px">Lint and validate check that the templates are well formed and follow best practice. They are separate from the security scan above.</p></section>
    <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" type="button" data-dl="reports">⤓ Scan reports (zip)</button><button class="btn" type="button" data-dl="report">⤓ Validation report (JSON)</button></div>`;
}

const ACTIONS = {
  "run.created": "Run created",
  "run.started": "Analysis started",
  "sow.extracted": "SOW text extracted",
  "phase.started": "Agent started",
  "phase.completed": "Agent step finished",
  "phase.continue": "Agent waiting (orchestrator resume)",
  "phase.failed": "Agent step failed",
  "bundle.rendered": "Code generated",
  "run.delivered": "Ready to download",
  "run.failed": "Run failed",
  "artifact.downloaded": "Download",
  "design.deploy_requested": "Deploy run requested",
  "deploy.started": "Deploy run started",
  "deploy.attested": "Foundation attested",
  "deploy.delivered": "Deploy finished",
  "deploy.failed": "Deploy failed",
  "tool.get_catalog": "Read the catalog",
  "tool.read_sow_page": "Read a SOW page",
  "tool.read_run_state": "Checked progress",
  "tool.save_scope": "Saved the scope",
  "tool.save_scope.rejected": "Scope rejected, retrying",
  "tool.save_scope.review": "Review hints sent to the agent",
  "tool.run_pre_discover": "Pre-deploy discovery",
  "tool.run_post_discover": "Post-deploy discovery",
  "tool.transform_init_connection": "Transform connection",
  "tool.transform_start_analyze": "Transform analyze started",
  "tool.transform_poll_analyze_job": "Transform analyze polled",
  "tool.transform_merge_discovery": "Merged Transform discovery",
  "tool.save_foundation_assessment": "Saved foundation assessment",
  "tool.save_iac_change_plan": "Saved IaC change plan",
  "tool.render_iac_bundles": "Rendered IaC bundles",
  "tool.transform_start_deploy": "Transform deploy started",
  "tool.transform_poll_deploy_job": "Transform deploy polled",
  "tool.finish_deploy_workflow": "Deploy workflow finished",
  "tool.yield_for_orchestrator": "Yielded for orchestrator",
  "run.stopped": "Run stopped",
  "tool.read_deploy_checkpoint": "Read deploy checkpoint",
  "tool.read_deploy_context": "Read deploy context",
  "tool.read_approved_scope": "Read approved scope",
};
function activityPanel(audit) {
  const rows = audit.filter((a) => S.steps || !a.action.startsWith("tool."));
  return `<label class="check" style="margin-bottom:10px"><input type="checkbox" id="steps" ${S.steps ? "checked" : ""}> Show the agent's individual steps</label>
    <div class="tbl-wrap"><table><thead><tr><th>When</th><th>Who</th><th>Event</th></tr></thead><tbody>${rows.map((a) =>
      `<tr><td style="white-space:nowrap;color:var(--dim)">${esc(new Date(a.ts * 1000).toLocaleTimeString())}</td><td>${esc(a.actor === claims.sub ? "You" : ["system", "agent"].includes(a.actor) ? a.actor[0].toUpperCase() + a.actor.slice(1) : "A user")}</td><td>${esc(ACTIONS[a.action] || a.action)}</td></tr>`).join("")}</tbody></table></div>`;
}

/* ---------- actions ---------- */
async function download(name) {
  try {
    const { url, filename } = await api(`/runs/${S.runId}/artifacts/${name}`);
    const a = Object.assign(document.createElement("a"), { href: url, download: filename });
    document.body.appendChild(a); a.click(); a.remove();
    toast("Download started");
  } catch (e) { if (e.message !== "session expired") toast(e.message, "bad"); }
}
let pendingDeployDesignId = null;

function deployAuthFields() {
  const method = $("deployForm").authMethod.value;
  $("deployRoleFields").hidden = method !== "role";
  $("deployKeyFields").hidden = method !== "keys";
  $("deployForm").accountId.required = method !== "platform";
  $("testDeployCreds").hidden = method === "platform";
  $("deployVerifyBox").hidden = true;
  $("deployVerifyBox").textContent = "";
  $("deployVerifyBox").className = "deploy-verify";
}

function setDeployVerifyResult(kind, text) {
  const box = $("deployVerifyBox");
  box.hidden = false;
  box.className = `deploy-verify ${kind}`;
  box.textContent = text;
}

async function testDeployCredentials() {
  const btn = $("testDeployCreds");
  try {
    const body = deployPayloadFromForm();
    btn.disabled = true;
    setDeployVerifyResult("pending", "Testing connection…");
    const r = await api("/deploy-target/verify", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      setDeployVerifyResult("err", r.error || "Could not verify credentials.");
      return;
    }
    let msg = r.message || "Credentials verified.";
    if (r.warnings && r.warnings.length) msg += " " + r.warnings.join(" ");
    setDeployVerifyResult("ok", msg);
  } catch (e) {
    if (e.message !== "session expired") setDeployVerifyResult("err", e.message);
  } finally {
    btn.disabled = false;
  }
}

function openDeployDialog(designRunId) {
  pendingDeployDesignId = designRunId;
  const f = $("deployForm");
  f.reset();
  f.authMethod.value = "role";
  deployAuthFields();
  $("deployDlg").showModal();
}

function deployPayloadFromForm() {
  const f = $("deployForm");
  const method = f.authMethod.value;
  if (method === "platform") return {};
  const accountId = f.accountId.value.trim();
  if (!/^\d{12}$/.test(accountId)) throw new Error("Target account ID must be 12 digits");
  if (method === "role") {
    const roleArn = f.roleArn.value.trim();
    if (!roleArn) throw new Error("Role ARN is required");
    const body = { deployTarget: { accountId, roleArn } };
    const ext = f.externalId.value.trim();
    if (ext) body.deployTarget.externalId = ext;
    return body;
  }
  const accessKeyId = f.accessKeyId.value.trim();
  const secretAccessKey = f.secretAccessKey.value.trim();
  if (!accessKeyId || !secretAccessKey) throw new Error("Access key ID and secret are required");
  const body = { deployTarget: { accountId, accessKeyId, secretAccessKey } };
  const sessionToken = f.sessionToken.value.trim();
  if (sessionToken) body.deployTarget.sessionToken = sessionToken;
  return body;
}

async function stopRun(runId) {
  if (!confirm("Stop this run? The workflow will abort and the run will be marked failed.")) return;
  try {
    await api(`/runs/${runId}/stop`, { method: "POST" });
    toast("Run stopped");
    await openRun(runId);
    loadRuns().catch(() => {});
  } catch (e) {
    if (e.message !== "session expired") toast(e.message, "bad");
  }
}

async function startDeploy(designRunId, body) {
  try {
    const { runId } = await api(`/runs/${designRunId}/deploy`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    toast("Deploy run started");
    await loadRuns().catch(() => {});
    location.hash = `#/run/${runId}`;
  } catch (e) {
    if (e.message !== "session expired") toast(e.message, "bad");
  }
}
function onView(e) {
  const row = e.target.closest("[data-open]");
  if (row && !e.target.closest("a,button")) { location.hash = `#/run/${row.dataset.open}`; return; }
  const deployBtn = e.target.closest("[data-deploy]");
  if (deployBtn) { openDeployDialog(deployBtn.dataset.deploy); return; }
  const stopBtn = e.target.closest("[data-stop-run]");
  if (stopBtn) { stopRun(stopBtn.dataset.stopRun); return; }
  const t = e.target.closest("[data-tab],[data-dl],[data-copy],[data-full]");
  if (!t) return;
  if (t.dataset.full) { const svg = diagramCache.get(S.data.diagram); if (svg) { $("fullBody").innerHTML = svg; $("full").showModal(); } }
  else if (t.dataset.tab) { S.tab = t.dataset.tab; renderRun(); const el = $("tab-" + S.tab); if (el) el.focus(); }
  else if (t.dataset.dl) download(t.dataset.dl);
  else if (t.dataset.copy !== undefined) {
    const text = JSON.stringify(S.data.scope.customScps[+t.dataset.copy].policy, null, 2);
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(() => toast("Policy copied"), () => toast("Copy isn't available here. Select the policy text instead.", "bad"));
  }
}
function onKeys(e) {
  if (!e.target.matches || !e.target.matches('[role="tab"]') || !["ArrowRight", "ArrowLeft"].includes(e.key)) return;
  const tabs = [...document.querySelectorAll('[role="tab"]')], i = tabs.indexOf(e.target);
  S.tab = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length].dataset.tab; renderRun(); $("tab-" + S.tab).focus(); e.preventDefault();
}

/* ---------- boot ---------- */
function route() {
  if (!token) return;
  clearTimeout(S.timer);
  const h = location.hash || "#/dashboard", run = (h.match(/^#\/run\/([0-9a-f]+)$/) || [])[1];
  if (run) { S.data = S.data && S.data.run.runId === run ? S.data : null; openRun(run); }
  else if (h === "#/runs") viewRuns();
  else viewDashboard();
  window.scrollTo(0, 0);
}
async function start() {
  claims = decodeJwt(token);
  $("gate").hidden = true; $("app").hidden = false;
  $("who").textContent = claims.email || "";
  $("logout").onclick = logout;
  $("closeFull").onclick = () => $("full").close();
  $("closeDeployDlg").onclick = () => $("deployDlg").close();
  $("cancelDeployDlg").onclick = () => $("deployDlg").close();
  $("deployForm").authMethod.onchange = deployAuthFields;
  $("testDeployCreds").onclick = () => testDeployCredentials();
  $("deployForm").onsubmit = async (e) => {
    e.preventDefault();
    if (!pendingDeployDesignId) return;
    try {
      const body = deployPayloadFromForm();
      $("deployDlg").close();
      await startDeploy(pendingDeployDesignId, body);
    } catch (err) {
      toast(err.message, "bad");
    }
  };
  $("view").addEventListener("click", onView);
  $("view").addEventListener("keydown", onKeys);
  $("view").addEventListener("change", (e) => { if (e.target.id === "steps") { S.steps = e.target.checked; renderRun(); } });
  window.addEventListener("hashchange", route);
  try { await loadRuns(); } catch (e) { if (e.message === "session expired") return; }
  route();
  // keep the Runs page fresh; never re-render the dashboard, which would wipe a half-filled form
  setInterval(() => { if (token && !document.hidden && location.hash === "#/runs") loadRuns().then(viewRuns).catch(() => {}); }, 30000);
}

(async () => {
  try {
    cfg = await (await fetch("/config.json", { cache: "no-store" })).json();
    const code = new URLSearchParams(location.search).get("code");
    try { token = code ? await exchange(code) : sessionStorage.getItem("idToken"); } catch { token = null; }
    const expired = token && jwtExpired(token);
    if (!token || expired) { sessionStorage.removeItem("idToken"); token = null; showGate(expired ? "Your session expired. Sign in again to continue." : ""); return; }
    await start();
  } catch (e) {  // never leave a blank page
    token = null;
    try { showGate(`The page could not finish loading (${e.message}). Refresh to try again.`); } catch { document.body.textContent = "The page could not load. Refresh to try again."; }
  }
})();
