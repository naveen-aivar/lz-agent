// Landing Zone Agent UI. Static SPA: Cognito Hosted UI (authorization code + PKCE) and the platform API.
// config.json is written by scripts/deploy.sh. No build step, no framework. Routes: #/dashboard, #/runs, #/run/<id>.
"use strict";

let cfg, token = null, claims = {};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const S = { runs: [], runId: "", data: null, tab: "organization", steps: false, file: null, timer: null,
  answer: { key: "", selected: null, draft: "", sending: false, error: "", expanded: false, reply: false },
  stale: false, feedSeen: 0, notified: new Set() };
// Cognito group allowed to answer AWS Transform from this UI (platform.yaml TransformApproversGroup).
const APPROVER_GROUP = "transform-approvers";

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
  const active = document.activeElement, focusId = active && $("view").contains(active) ? active.id : "";
  const caret = focusId && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null;
  $("view").innerHTML = html;
  const again = focusId && $(focusId);
  if (again) { again.focus({ preventScroll: true }); if (caret && again.setSelectionRange) again.setSelectionRange(...caret); }
}

/* ---------- safe markdown (Transform messages are untrusted: escape first, then a small fixed subset) ---------- */
const mdInline = (escaped) => escaped
  .replace(/`([^`]+)`/g, "<code>$1</code>")
  .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
  .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>");
function md(src) {
  const lines = String(src || "").replace(/\r/g, "").split("\n"), out = [];
  const cells = (row) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  const isSep = (row) => cells(row).every((c) => /^:?-{2,}:?$/.test(c));
  let para = [];
  const flush = () => { if (para.length) out.push(`<p>${para.map((l) => mdInline(esc(l))).join("<br>")}</p>`); para = []; };
  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    if (/^\s*\|/.test(line)) {
      flush();
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      const head = rows.length > 1 && isSep(rows[1]) ? cells(rows[0]) : null;
      const body = rows.filter((r, k) => !isSep(r) && !(head && k === 0));
      out.push(`<div class="tbl-wrap"><table>${head ? `<thead><tr>${head.map((c) => `<th>${mdInline(esc(c))}</th>`).join("")}</tr></thead>` : ""}<tbody>${body.map((r) => `<tr>${cells(r).map((c) => `<td>${mdInline(esc(c))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    const ul = /^\s*[-*•]\s+(.*)$/, ol = /^\s*\d+[.)]\s+(.*)$/;
    if (ul.test(line) || ol.test(line)) {
      flush();
      const re = ul.test(line) ? ul : ol, tag = re === ul ? "ul" : "ol", items = [];
      while (i < lines.length && re.test(lines[i])) items.push(lines[i++].match(re)[1]);
      out.push(`<${tag}>${items.map((t) => `<li>${mdInline(esc(t))}</li>`).join("")}</${tag}>`);
      continue;
    }
    const h = line.match(/^\s*#{1,6}\s+(.*)$/);
    if (h) { flush(); out.push(`<p class="md-h">${mdInline(esc(h[1]))}</p>`); i++; continue; }
    if (!line.trim()) { flush(); i++; continue; }
    para.push(line); i++;
  }
  flush();
  return out.join("");
}
const userGroups = () => { const g = claims["cognito:groups"]; return Array.isArray(g) ? g : typeof g === "string" ? [g] : []; };
const canAnswerTransform = () => userGroups().includes(APPROVER_GROUP);

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
    if (first) S.feedSeen = 0;
    S.data = { run, audit, scope, diagram, report, deploymentReport };
    if (first || (!hadScope && scope)) {
      if (isDeployRun(run)) S.tab = deploymentReport ? "deployment" : scope ? "organization" : "activity";
      else S.tab = scope ? "organization" : "activity";
    }
    S.stale = false;
    renderRun();
    notifyHumanInput(run);
    clearTimeout(S.timer);
    if (!isDone(run)) S.timer = setTimeout(() => openRun(id, { silent: true }), 4000);
    else loadRuns().catch(() => {});
  } catch (e) {
    if (e.message === "session expired") return;
    if (!silent) { toast(e.message === "not found" ? "That run isn't available to you." : e.message, "bad"); location.hash = "#/runs"; return; }
    // A failed background refresh: say so and keep trying instead of freezing on old data.
    if (S.runId === id && S.data) {
      S.stale = true; renderRun();
      clearTimeout(S.timer); S.timer = setTimeout(() => openRun(id, { silent: true }), 8000);
    }
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
  const waitingOnPerson = run.status === "RUNNING" && (run.awaitingHitl === true || !!run.pendingHumanInput);
  const has = (a) => audit.some((x) => x.action === a);
  const hasTool = (name) => audit.some((x) => x.action === name);
  const jobDone = audit.some((x) => x.action === "tool.transform_poll_analyze_job" && parseAuditDetail(x).done === true);
  const done = [
    hasTool("tool.run_pre_discover") || hasTool("tool.run_pre_discover.failed"),
    jobDone,
    hasTool("tool.save_iac_change_plan") || hasTool("tool.render_iac_bundles"),
    has("deploy.attested") || (run.status === "DELIVERED" && has("phase.completed")),
  ];
  const steps = [
    ["Discover baseline", "Organizations snapshot and gap analysis"],
    ["Build with AWS Transform", "Transform plans and builds; the deploy agent answers from the design"],
    ["Assess and plan", "Foundation assessment and IaC change plan"],
    ["Attest and deliver", "Foundation report and artifacts"],
  ];
  const next = done.indexOf(false), failed = run.status === "FAILED";
  return `<div class="steps">${steps.map(([name, sub], i) => {
    const state = done[i] ? "done" : i === next ? (failed ? "failed" : run.status === "AWAITING_INPUT" ? "" : "active") : "";
    const waiting = state === "active" && waitingOnPerson;
    const subText = done[i] ? "Done" : state === "failed" ? "Stopped here" : waiting ? "Waiting for your answer" : state === "active" ? "In progress" : sub;
    return `<div class="step ${state}${waiting ? " waiting" : ""}"><div class="step-rail"><span class="step-node"></span><span class="step-line"></span></div>
      <div class="step-body"><div class="step-name">${esc(name)}</div><div class="step-sub">${esc(subText)}</div></div>
      <span class="step-check">${done[i] ? "✓" : state === "failed" ? "✕" : ""}</span></div>`;
  }).join("")}</div>`;
}

function deployContinueNotice(audit, run) {
  const lastCont = [...audit].reverse().find((a) => a.action === "phase.continue");
  const lastYield = [...audit].reverse().find((a) => a.action === "tool.yield_for_orchestrator");
  const d = lastCont ? parseAuditDetail(lastCont) : {};
  const reason = String(d.reason || (lastYield ? parseAuditDetail(lastYield).reason : "") || "").trim();
  if (!lastCont && !reason) return "";
  // Routine waits while the Transform job runs are shown by the progress steps and the question card, not as a pause.
  if (/^transform_analyze_waiting$|already polled this invoke$|^deploy_judgment complete/.test(reason)) return "";
  const targetAcct = run && run.deployTarget && run.deployTarget.accountId;
  if (/^Pre-discover failed for deploy target account/i.test(reason)) {
    return `<div class="notice notice-warn" role="status"><strong>Deploy paused (target discover).</strong> ${esc(reason.length > 480 ? reason.slice(0, 480) + "…" : reason)}<br><span class="hint">Fix the issue in ${targetAcct ? `account ${esc(targetAcct)}` : "the target account"}, then start a new deploy run.</span></div>`;
  }
  const platformBlock =
    /permission|IAM|AccessDenied|not authorized|s3:|organization|create-organization|platform account|run_pre_discover|NotInUse/i.test(
      reason
    );
  if (d.awaitingHitl && !platformBlock) {
    return `<div class="notice notice-info" role="status"><strong>Waiting on AWS Transform.</strong> Complete the required step in the Transform workspace. The deploy agent will resume on its own.</div>`;
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

// META.pendingHumanInput (phase_invoke) mirrors the question an AWS Transform job is waiting on.
// Everything from Transform is untrusted text: md() escapes it, and only https console URLs are linked.
// Message questions can be answered here (POST /runs/{id}/answer, approver group); tasks need Transform's own form.
const questionKey = (p) => (p ? `${p.jobId}:${p.messageId || p.taskId || p.title}` : "");
function answerState(p) {
  const key = questionKey(p);
  if (S.answer.key !== key) S.answer = { key, selected: null, draft: "", sending: false, error: "", expanded: false, reply: false };
  return S.answer;
}
function askedAt(audit, p) {
  const row = [...audit].reverse().find((a) => a.action === "phase.awaiting_human" && parseAuditDetail(a).jobId === p.jobId);
  return row ? row.ts : null;
}
function humanInputBanner(run, audit = []) {
  if (run.status !== "RUNNING") return "";
  const p = run.pendingHumanInput && typeof run.pendingHumanInput === "object" ? run.pendingHumanInput : null;
  if (!p && run.awaitingHitl !== true) return "";
  const url = p && typeof p.consoleUrl === "string" && /^https:\/\//i.test(p.consoleUrl) ? p.consoleUrl : "";
  const openLink = url ? `<a class="btn btn-sm" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open in AWS Transform ↗<span class="sr-only"> (opens in a new tab)</span></a>` : "";
  if (!p) {
    return `<section class="hitl" role="region" aria-labelledby="hitl-heading"><div class="hitl-head"><span class="pulse" aria-hidden="true"></span><h2 id="hitl-heading">AWS Transform is waiting for a person</h2></div>
      <p>Transform did not return the question. Open the job in the Transform workspace to answer it.</p></section>`;
  }
  const a = answerState(p);
  const options = Array.isArray(p.options) ? p.options.filter((o) => typeof o === "string" && o) : [];
  const note = p.agentNote && typeof p.agentNote === "object" && p.agentNote.reason ? p.agentNote : null;
  const answered = run.pendingAnswer && p.messageId && run.pendingAnswer.messageId === p.messageId ? run.pendingAnswer : null;
  const asked = askedAt(audit, p);
  const text = String(p.text || "");
  const long = text.length > 700 || text.split("\n").length > 14;
  const question = text
    ? `<div class="hitl-q md ${long && !a.expanded ? "clamp" : ""}" id="hitl-text">${md(text)}</div>
       ${long ? `<button class="btn-link" type="button" data-hitl-expand aria-expanded="${a.expanded}" aria-controls="hitl-text">${a.expanded ? "Show less" : "Show the full message"}</button>` : ""}`
    : "";
  let action;
  if (answered) {
    const byAgent = answered.by === "agent";
    const what = answered.option ? `“${esc(answered.option)}”` : byAgent ? "a reply" : "your message";
    const who = byAgent ? "(by the deploy agent) " : answered.by === claims.sub ? "" : "(by another user) ";
    action = `<div class="hitl-sent" role="status"><span class="spin spin-green" aria-hidden="true"></span><div><strong>Sent ${what} to AWS Transform</strong> ${who}· ${esc(ago(answered.at))}
      <div class="hint">Waiting for Transform to continue. This page updates on its own.</div>${answered.text ? `<blockquote class="quote">${esc(answered.text)}</blockquote>` : ""}</div></div>`;
  } else if (p.kind === "message" && p.messageId && canAnswerTransform()) {
    const busy = a.sending ? "disabled" : "";
    const choices = options.length ? `<div class="choices" role="group" aria-label="Choose an answer">${options.map((o, k) =>
      `<button class="choice" type="button" id="choice-${k}" data-answer-option="${k}" aria-pressed="${a.selected === o}" ${busy}>${esc(o)}</button>`).join("")}</div>` : "";
    const confirm = !options.length ? "" : a.selected !== null
      ? `<div class="confirm" role="group" aria-label="Confirm answer"><span>Send <strong>“${esc(a.selected)}”</strong> to AWS Transform?</span>
          <span class="confirm-actions"><button class="btn btn-primary btn-sm" type="button" id="answer-send" data-answer-send ${busy}>${a.sending ? '<span class="spin"></span> Sending…' : "Send answer"}</button>
          <button class="btn btn-sm" type="button" data-answer-cancel ${busy}>Cancel</button></span></div>`
      : `<p class="hint">Pick an option, then confirm. You can also reply with your own message.</p>`;
    const n = a.draft.trim().length;
    const reply = a.reply || !options.length
      ? `<div class="reply"><label class="lbl" for="answer-text">Your reply to Transform</label>
          <textarea class="textarea" id="answer-text" maxlength="4000" rows="3" placeholder="For example: add eu-west-1 as a second governed region" ${busy}>${esc(a.draft)}</textarea>
          <div class="reply-foot"><span class="hint" id="answer-count">${n}/4000 · Ctrl+Enter to send</span>
          <span>${options.length ? `<button class="btn btn-sm" type="button" data-answer-reply-close ${busy}>Close</button>` : ""}
          <button class="btn btn-primary btn-sm" type="button" id="answer-text-send" data-answer-text ${n && !a.sending ? "" : "disabled"}>${a.sending && a.selected === null ? '<span class="spin"></span> Sending…' : "Send reply"}</button></span></div></div>`
      : `<button class="btn-link" type="button" id="answer-reply-open" data-answer-reply-open ${busy}>Reply with a message instead</button>`;
    action = `${choices}${confirm}${reply}${a.error ? `<p class="errtext" role="alert" style="margin:10px 0 0">${esc(a.error)}</p>` : ""}`;
  } else if (p.kind === "message") {
    action = `${options.length ? `<div class="choices">${options.map((o) => `<span class="choice choice-ro">${esc(o)}</span>`).join("")}</div>` : ""}
      <p class="hint">${p.messageId ? `Only members of the <code>${APPROVER_GROUP}</code> group can answer from here. Ask an administrator to add you, or answer in AWS Transform.` : "Answer in AWS Transform."}</p>`;
  } else {
    action = `<p class="hint">${p.kind === "task" ? "This is a Transform task with its own form. Open it in AWS Transform to complete it." : "Answer in AWS Transform."}</p>`;
  }
  return `<section class="hitl" role="region" aria-labelledby="hitl-heading">
    <div class="hitl-head"><span class="pulse" aria-hidden="true"></span><h2 id="hitl-heading">${answered ? "Answer sent to AWS Transform" : "AWS Transform needs your input"}</h2>
      ${asked ? `<span class="hint" style="margin:0">asked ${esc(ago(asked))}</span>` : ""}<span class="hitl-link">${openLink}</span></div>
    ${p.title && p.kind === "task" ? `<p style="margin:0 0 8px"><strong>${esc(p.title)}</strong></p>` : ""}
    ${question}${note && !answered ? `<div class="agent-note" role="note"><strong>Deploy agent:</strong> ${esc(note.reason)}${note.suggestion ? `<div class="hint">Suggested: ${esc(note.suggestion)}</div>` : ""}${typeof note.link === "string" && /^https:\/\/[a-z0-9-]+\.console\.aws\.amazon\.com\//.test(note.link) ? `<div style="margin-top:8px"><a class="btn btn-sm btn-primary" href="${esc(note.link)}" target="_blank" rel="noopener noreferrer">Approve in the AWS console ↗<span class="sr-only"> (opens in a new tab)</span></a></div>` : ""}</div>` : ""}${action}
    <p class="hint" style="margin-top:12px">Transform job <code>${esc(p.jobId || "")}</code>. The deploy resumes on its own once Transform has your answer. It fails if no answer arrives within about 24 hours.</p></section>`;
}

async function sendAnswer(payload) {
  const run = S.data && S.data.run, p = run && run.pendingHumanInput;
  if (!p || S.answer.sending) return;
  S.answer.sending = true; S.answer.error = ""; renderRun();
  try {
    const r = await api(`/runs/${run.runId}/answer`, { method: "POST", body: JSON.stringify({ jobId: p.jobId, messageId: p.messageId, ...payload }) });
    if (S.data && S.data.run.runId === run.runId) S.data.run.pendingAnswer = r.pendingAnswer;
    toast("Answer sent to AWS Transform");
  } catch (e) {
    if (e.message === "session expired") return;
    S.answer.error = e.message;
  } finally {
    S.answer.sending = false;
    if (S.data && S.data.run.runId === run.runId) { renderRun(); openRun(run.runId, { silent: true }); }
  }
}

// Toast when a question arrives while the page is open (not for one already waiting when the run was opened).
function notifyHumanInput(run) {
  const p = run.status === "RUNNING" && run.pendingHumanInput;
  const key = p ? questionKey(p) : "";
  if (S.notifyRun !== run.runId) { S.notifyRun = run.runId; if (key) S.notified.add(key); return; }
  if (!key || S.notified.has(key)) return;
  S.notified.add(key);
  toast("AWS Transform needs your input");
}
const needsAnswer = (run) => {
  const p = run.status === "RUNNING" && run.pendingHumanInput;
  return !!p && !(run.pendingAnswer && p.messageId && run.pendingAnswer.messageId === p.messageId);
};

const FEED_SKIP = new Set(["deploy.sequencer.step", "phase.continue", "phase.started", "tool.transform_poll_analyze_job",
  "tool.read_deploy_checkpoint", "tool.read_deploy_context", "tool.read_approved_scope", "tool.yield_for_orchestrator"]);
function feedText(a) {
  const d = parseAuditDetail(a);
  if (a.action === "transform.answer_sent") return `${a.actor === "agent" ? "Deploy agent" : a.actor === claims.sub ? "You" : "A user"} answered ${d.option ? `“${d.option}”` : "with a message"}`;
  if (a.action === "transform.agent_escalated") return `Deploy agent handed you: ${d.title || "a Transform question"}`;
  if (a.action === "phase.awaiting_human" && d.title) return `Transform asked: ${d.title}`;
  if (a.action.endsWith(".failed") && d.error) return `${ACTIONS[a.action] || a.action}: ${String(d.error).slice(0, 140)}`;
  return ACTIONS[a.action] || a.action;
}
function activityFeed(audit) {
  const rows = audit.filter((a) => !FEED_SKIP.has(a.action)).slice(-7).reverse();
  const seen = S.feedSeen; S.feedSeen = Math.max(seen, ...audit.map((a) => a.ts || 0));
  if (!rows.length) return "";
  return `<div class="card"><div class="card-head"><h2>Latest activity</h2><button class="btn-link" type="button" data-tab="activity">All events</button></div>
    <ol class="feed" aria-live="polite">${rows.map((a) => `<li class="${seen && a.ts > seen ? "new" : ""} ${/failed/.test(a.action) ? "bad" : ""}"><time datetime="${new Date(a.ts * 1000).toISOString()}" title="${esc(new Date(a.ts * 1000).toLocaleString())}">${esc(ago(a.ts))}</time><span>${esc(feedText(a))}</span></li>`).join("")}</ol></div>`;
}
const liveBadge = (run) => (isDone(run) ? "" : S.stale
  ? '<span class="live stale" role="status"><i aria-hidden="true"></i>Reconnecting…</span>'
  : '<span class="live" title="This page refreshes every few seconds"><i aria-hidden="true"></i>Live</span>');

function credentialsCleanupNotice(run) {
  if (!run.credentialsCleanupError) return "";
  return `<div class="notice notice-err" role="alert"><strong>Stored target credentials were not deleted.</strong> ${esc(run.credentialsCleanupError)}<br><span class="hint">Ask a platform operator to delete them from the artifact bucket and rotate the access key.</span></div>`;
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
    <div class="page-title" style="display:flex;flex-wrap:wrap;align-items:center;gap:10px">${esc(name)} ${runTypeBadge(run)} ${stateBadge(run)} ${liveBadge(run)} ${stopRunButton(run)}</div>
    <p class="page-sub" style="margin-bottom:18px">Started ${esc(when(run.createdAt))} · Deploy run <code>${esc(run.runId.slice(0, 8))}</code>${designLink}</p>
    ${failure}${credentialsCleanupNotice(run)}${humanInputBanner(run, audit) || deployContinueNotice(audit, run)}
    <div class="grid-3"><div class="card"><div class="card-head"><h2>Progress</h2></div>${deployStepsHtml(run, audit)}</div>${activityFeed(audit)}${deployDeliverables(run)}</div>
    ${body}`);
  if (needsAnswer(run)) document.title = `● Input needed · ${document.title}`;
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
  "phase.awaiting_human": "AWS Transform asked for your input",
  "phase.human_input_resolved": "Transform input received",
  "deploy.target_credentials_deleted": "Stored target credentials deleted",
  "deploy.target_credentials_delete_failed": "Deleting stored target credentials failed",
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
  "tool.finish_deploy_workflow": "Deploy workflow finished",
  "tool.yield_for_orchestrator": "Yielded for orchestrator",
  "run.stopped": "Run stopped",
  "tool.read_deploy_checkpoint": "Read deploy checkpoint",
  "tool.read_deploy_context": "Read deploy context",
  "tool.read_approved_scope": "Read approved scope",
  "transform.answer_sent": "Answer sent to AWS Transform",
  "transform.answer_failed": "Sending an answer to AWS Transform failed",
  "transform.agent_escalated": "Deploy agent handed a Transform question to you",
  "transform.agent_turn_failed": "Deploy agent could not decide on a Transform question",
  "transform.agent_converse_failed": "Deploy agent gave up on a Transform question",
  "deploy.sequencer.step": "Deploy step",
  "tool.transform_start_analyze.failed": "Transform analyze failed",
  "tool.transform_poll_analyze_job.failed": "Transform analyze poll failed",
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
  $("deployForm").roleArn.required = method === "role";
  $("deployForm").externalId.required = method === "role";
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
    if (!pendingDeployDesignId) throw new Error("Open this dialog from a delivered design run");
    // The API only tests credentials for the owner of a DELIVERED design run.
    const body = { ...deployPayloadFromForm(), designRunId: pendingDeployDesignId };
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
    const externalId = f.externalId.value.trim();
    if (!externalId) throw new Error("External ID is required for the IAM role method");
    return { deployTarget: { accountId, roleArn, externalId } };
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
  const opt = e.target.closest("[data-answer-option]");
  if (opt) {
    const p = S.data.run.pendingHumanInput, o = p && p.options[+opt.dataset.answerOption];
    S.answer.selected = S.answer.selected === o ? null : o; S.answer.error = ""; renderRun();
    const send = $("answer-send"); if (send) send.focus();
    return;
  }
  if (e.target.closest("[data-answer-send]")) { if (S.answer.selected !== null) sendAnswer({ option: S.answer.selected }); return; }
  if (e.target.closest("[data-answer-cancel]")) { S.answer.selected = null; renderRun(); return; }
  if (e.target.closest("[data-answer-reply-open]")) { S.answer.reply = true; S.answer.selected = null; renderRun(); const t = $("answer-text"); if (t) t.focus(); return; }
  if (e.target.closest("[data-answer-reply-close]")) { S.answer.reply = false; renderRun(); return; }
  if (e.target.closest("[data-answer-text]")) { const t = S.answer.draft.trim(); if (t) { S.answer.selected = null; sendAnswer({ text: t }); } return; }
  if (e.target.closest("[data-hitl-expand]")) { S.answer.expanded = !S.answer.expanded; renderRun(); return; }
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
  if (e.target.id === "answer-text" && e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault(); const t = S.answer.draft.trim(); if (t && !S.answer.sending) sendAnswer({ text: t }); return;
  }
  if (e.target.id === "answer-text" && e.key === "Escape") { S.answer.reply = false; renderRun(); return; }
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
  // Keep the reply draft in state (the page re-renders every few seconds) and update its counter in place.
  $("view").addEventListener("input", (e) => {
    if (e.target.id !== "answer-text") return;
    S.answer.draft = e.target.value;
    const n = S.answer.draft.trim().length, c = $("answer-count"), b = $("answer-text-send");
    if (c) c.textContent = `${n}/4000 · Ctrl+Enter to send`;
    if (b) b.disabled = !n || S.answer.sending;
  });
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
