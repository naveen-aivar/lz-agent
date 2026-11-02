#!/usr/bin/env node
// Brings the Architecture Design Agent's screens from the isolated UI (read only) into the dashboard.
//
//   node agents/architecture-design/port.mjs            writes src/features/architecture-design/app/ and public/agents/architecture-design/
//   node agents/architecture-design/port.mjs --check    rebuilds that output in a scratch folder and compares it (exit 1 if it differs)
//   options   --source <dir>   the isolated ui-app folder (default: $ARCH_UI_DIR)
//             --out <dir>      where app/ is written
//
// The isolated repository is only read. The dashboard draws the sidebar, the top bar and the toaster, so those files are left out.
// Each scripted edit must match exactly once, so a change in the isolated source stops the script instead of being half-applied.
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { scopeCss } from '../../scripts/scope-css.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '../..');
const SCOPE = 'mm-architecture-design';
const LEFT_OUT = new Set(['main.jsx', 'App.jsx', 'components/Sidebar.jsx', 'components/Topbar.jsx']);
const CSS = ['styles/tokens.css', 'styles/base.css', 'styles/shell.css', 'styles/ui.css', 'styles/stepper.css', 'styles/arch.css'];

const args = process.argv.slice(2);
const option = (name) => (args.includes(`--${name}`) ? args[args.indexOf(`--${name}`) + 1] : undefined);
const CHECK = args.includes('--check');
const SOURCE = path.resolve(option('source') ?? process.env.ARCH_UI_DIR ?? '');
const OUT = path.resolve(option('out') ?? path.join(REPO, 'src/features/architecture-design/app'));
const PUBLIC = path.resolve(option('public') ?? path.join(REPO, 'public/agents/architecture-design'));

const fail = (message) => {
  console.error(`port.mjs: ${message}`);
  process.exit(1);
};
if (!SOURCE) fail('set --source or ARCH_UI_DIR to the isolated deployment/ui-app folder');

function walk(dir, base = dir) {
  const found = [];
  for (const name of readdirSync(dir).sort()) {
    if (name.startsWith('.')) continue;
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) found.push(...walk(full, base));
    else found.push(path.relative(base, full).split(path.sep).join('/'));
  }
  return found;
}

function once(text, from, to, label) {
  const parts = text.split(from);
  if (parts.length !== 2) fail(`${label} matched ${parts.length - 1} times, expected 1`);
  return parts.join(to);
}

function build() {
  const src = path.join(SOURCE, 'src');
  if (!statSync(src).isDirectory()) fail(`${src} is not the isolated src folder`);
  const files = new Map();
  for (const rel of walk(src)) {
    if (LEFT_OUT.has(rel) || rel.startsWith('styles/')) continue;
    let text = readFileSync(path.join(src, rel), 'utf8');
    if (rel === 'api.js') {
      text = once(
        text,
        `const BASE = (import.meta.env.PROD && import.meta.env.VITE_API_BASE)
  ? String(import.meta.env.VITE_API_BASE).replace(/\\/$/, "")
  : "/api";`,
        'const BASE = "/agents/architecture-design/api";',
        'api base',
      );
      // The dashboard's key gate holds the access key: every call carries the signed-in person's ID token instead, and a
      // refused call means "sign in again", never a key prompt (infra/README.md: Key gates).
      text = once(
        text,
        'import { sampleRun } from "./sampleRun.js";',
        'import { sampleRun } from "./sampleRun.js";\nimport { idToken } from "@/shared/auth/cognito";',
        'id token import',
      );
      text = once(
        text,
        `  const headers = { "Content-Type": "application/json" };
  const key = readKey();
  if (key) headers["X-Access-Key"] = key;
  const resp = await fetch(\`\${BASE}\${path}\`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await resp.json().catch(() => ({}));
  if (resp.status === 401 && !retried) {
    if (await askKey(!!key)) return req(method, path, body, true);
  }
  if (!resp.ok) throw new Error(data.error || data.message || \`HTTP \${resp.status}\`);`,
        `  const headers = { "Content-Type": "application/json" };
  const token = await idToken().catch(() => null);
  if (token) headers.Authorization = \`Bearer \${token}\`;
  const resp = await fetch(\`\${BASE}\${path}\`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await resp.json().catch(() => ({}));
  if (resp.status === 401) throw new Error("Sign in again to use this.");
  if (!resp.ok) throw new Error(data.error?.message || data.error || data.message || \`HTTP \${resp.status}\`);`,
        'gate sign-in instead of the access key',
      );
      // What only the key prompt used. writeKey and answerKey stay: the unused AccessKeyDialog still imports answerKey.
      text = once(text, 'const readKey = () => { try { return sessionStorage.getItem(KEY_STORE) || ""; } catch { return ""; } };\n', '', 'unused readKey');
      text = once(
        text,
        `function askKey(wrong) {
  if (!keyPrompt) {
    keyPrompt = new Promise((resolve) => { keyResolve = resolve; });
    window.dispatchEvent(new CustomEvent("accesskey:ask", { detail: { wrong } }));
  }
  return keyPrompt;
}
`,
        '',
        'unused askKey',
      );
      text = once(text, 'async function req(method, path, body, retried = false) {', 'async function req(method, path, body) {', 'req signature');
      text = once(text, 'let keyPrompt = null;\n', '', 'unused keyPrompt');
      text = once(text, '  keyPrompt = null;\n', '', 'unused keyPrompt reset');
    }
    if (rel === 'sampleRun.js') {
      text = once(
        text,
        'const BUNDLE_URL = `${import.meta.env.BASE_URL}sample_run/bundle.json`;',
        'const BUNDLE_URL = "/agents/architecture-design/sample_run/bundle.json";',
        'sample bundle url',
      );
    }
    if (rel === 'pages/NewArchitecture.jsx') {
      text = once(
        text,
        'const resp = await fetch(`${import.meta.env.BASE_URL}sample_srs.md`);',
        'const resp = await fetch("/agents/architecture-design/sample_srs.md");',
        'sample requirements url',
      );
    }
    if (rel === 'useRoute.js') {
      text = `// The dashboard has no address per page. Links and navigate() go through the shell (adapters/route.js).\nexport { href, navigate } from "@/features/architecture-design/adapters/route.js";\n`;
    }
    if (rel === 'components/ui/Modal.jsx') {
      text = once(text, 'import { X } from "lucide-react";', 'import { X } from "lucide-react";\nimport { portalContainer } from "@/features/architecture-design/adapters/portal.js";', 'modal import');
      text = once(text, '<Dialog.Portal>', '<Dialog.Portal container={portalContainer()}>', 'modal portal');
    }
    if (rel === 'components/ui/SearchableSelect.jsx') {
      text = once(text, 'import { Check, ChevronsUpDown, Search } from "lucide-react";', 'import { Check, ChevronsUpDown, Search } from "lucide-react";\nimport { portalContainer } from "@/features/architecture-design/adapters/portal.js";', 'select import');
      text = once(text, '<Popover.Portal>', '<Popover.Portal container={portalContainer()}>', 'select portal');
    }
    if (rel === 'run/flow.js') {
      text = once(
        text,
        '  if (cur.awaiting === "lz_approval" || !run.lz_approved) return STEP.landing;',
        '  // Some runs have a finished design and no landing-zone record. Those open on the design, not an empty landing zone.',
        'landing zone when the run has one',
      );
      text = once(
        text,
        '  // Some runs have a finished design and no landing-zone record. Those open on the design, not an empty landing zone.',
        '  if ((cur.awaiting === "lz_approval" || !run.lz_approved) && lzVersions(cur).length) return STEP.landing;',
        'open the design when there is no landing zone',
      );
    }
    if (rel === 'run/LandingZoneStep.jsx') {
      text = once(
        text,
        'import { ModelCalls, StatusBadge, Waiting } from "../components/bits.jsx";',
        'import { ModelCalls, StatusBadge, Waiting } from "../components/bits.jsx";\nimport LandingScene from "@/features/architecture-design/landing-scene.jsx";',
        'landing scene import',
      );
      text = once(
        text,
        '  if (!list.length) return <Waiting>Designing the landing zone…</Waiting>;',
        '  if (!list.length) return busy ? <LandingScene /> : <p className="tone-muted">This run has no landing zone of its own. The design is on the next step.</p>;',
        'empty landing zone',
      );
    }
    if (rel === 'pages/RunDetail.jsx') {
      text = once(
        text,
        'actions={<button type="button" className="btn btn-step btn-md" disabled aria-hidden tabIndex={-1}><SkeletonText>Approve landing zone 1</SkeletonText></button>}>',
        'actions={<button type="button" className="btn btn-step btn-md" data-solid="true" disabled aria-hidden tabIndex={-1}><SkeletonText>Approve landing zone 1</SkeletonText></button>}>',
        'loading approve button stays solid',
      );
    }
    if (rel === 'pages/Runs.jsx') {
      text = once(
        text,
        '  const newButton = <ButtonLink href={href("new")}><FilePlus2 size={16} aria-hidden /> New architecture</ButtonLink>;',
        '  const newButton = loading\n    ? <button type="button" className="btn btn-primary btn-md" disabled><FilePlus2 size={16} aria-hidden /> New architecture</button>\n    : <ButtonLink href={href("new")}><FilePlus2 size={16} aria-hidden /> New architecture</ButtonLink>;',
        'new architecture stays put while the list loads',
      );
    }
    // Loading is grey bars shaped like the content, never a spinner and a sentence. The sentence stays for screen readers.
    if (rel === 'components/bits.jsx') {
      text = once(
        text,
        'import { Notice } from "./ui/Notice.jsx";',
        'import { Notice } from "./ui/Notice.jsx";\nimport { Skeleton } from "./ui/Skeleton.jsx";',
        'skeleton import in bits',
      );
      text = once(
        text,
        `// One plain sentence while something is still being made (instead of lone grey bars).
export function Waiting({ children }) {
  return (
    <p className="waiting"><LoaderCircle size={16} className="spin" aria-hidden /> <span>{children}</span></p>
  );
}`,
        `// Something is still being made: grey bars shaped like the content that will appear. The sentence is for screen readers.
export function Waiting({ children }) {
  return (
    <div className="waiting" role="status" aria-live="polite">
      <span className="sr-only">{children}</span>
      <Skeleton className="waiting-line" />
      <Skeleton className="waiting-line waiting-line-short" />
      <Skeleton className="waiting-block" />
    </div>
  );
}`,
        'waiting is a skeleton',
      );
    }
    if (rel === 'run/DesignStep.jsx') {
      text = once(
        text,
        'import { Notice } from "../components/ui/Notice.jsx";\nimport SearchableSelect',
        'import { Notice } from "../components/ui/Notice.jsx";\nimport { SkeletonText } from "../components/ui/Skeleton.jsx";\nimport SearchableSelect',
        'skeleton text import in design step',
      );
      text = once(
        text,
        '    return <Waiting>{run.lz_approved ? "The design starts in a moment." : "The design starts after the landing zone is approved."}</Waiting>;',
        '    return run.lz_approved\n      ? <Waiting>The design starts in a moment.</Waiting>\n      : <p className="tone-muted">The design starts after the landing zone is approved.</p>;',
        'a blocked design is a sentence, not a loading state',
      );
      text = once(
        text,
        '        <Waiting>{v.status === "failed" ? "This version has no outputs." : "The outputs appear here as each step finishes."}</Waiting>',
        '        v.status === "failed"\n          ? <p className="tone-muted">This version has no outputs.</p>\n          : <Waiting>The outputs appear here as each step finishes.</Waiting>',
        'a failed version is a sentence, not a loading state',
      );
      text = once(text, 'const waValue = !r.status ? "…" : r.status === "failed"', 'const waValue = !r.status ? <SkeletonText>00%</SkeletonText> : r.status === "failed"', 'score tile skeleton');
      text = once(text, 'd.status === "failed" ? "Failed" : "…";', 'd.status === "failed" ? "Failed" : <SkeletonText>Passed</SkeletonText>;', 'diagram tile skeleton');
      text = once(text, 'value={services !== undefined ? num(services) : "…"}', 'value={services !== undefined ? num(services) : <SkeletonText>00</SkeletonText>}', 'services tile skeleton');
    }
    files.set(rel, text);
  }
  let css = CSS.map((rel) => readFileSync(path.join(src, rel), 'utf8')).join('\n');
  // The isolated app paints a white pill behind a solid header button so it reads over its own blue corner.
  // In the dashboard that pill shows as a white card beside the Approve button, including while it is still a skeleton.
  // TCO's main button is the blue pill itself, with no tray behind it.
  css = once(
    css,
    '.page-header-actions:has(.btn-primary, .btn-step) { padding: 0.25rem; border: 1px solid var(--color-gray-100); border-radius: var(--radius-pill); background: var(--color-surface); box-shadow: var(--shadow-md); }',
    '.page-header-actions:has(.btn-primary, .btn-step) { padding: 0; border: 0; background: none; box-shadow: none; width: max-content; margin-left: auto; }',
    'no white tray behind the approve button',
  );
  // The plain tray (no :has) still paints a white card at 1200px. The button itself keeps a white edge so it reads on the blue corner.
  css = once(
    css,
    '.page-header-actions { padding: 0.25rem; border: 1px solid var(--color-gray-100); border-radius: var(--radius-pill); background: var(--color-surface); box-shadow: var(--shadow-md); }',
    '.page-header-actions .btn-primary, .page-header-actions .btn-step { border-color: #fff; }',
    'header button has a white edge and no tray',
  );
  css = once(
    css,
    `  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-primary-600) 50%, transparent);
  color: #fff;`,
    `  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-primary-600) 50%, white);
  color: #fff;`,
    'step button stays opaque',
  );
  files.set('architecture.css', scopeCss(css, SCOPE));
  const pub = path.join(SOURCE, 'public');
  const publicFiles = new Map();
  if (statSync(pub, { throwIfNoEntry: false })?.isDirectory()) {
    for (const rel of walk(pub)) publicFiles.set(rel, readFileSync(path.join(pub, rel)));
  }
  return { files, publicFiles };
}

function writeTree(dir, files, binary = false) {
  rmSync(dir, { recursive: true, force: true });
  for (const [rel, contents] of files) {
    const dest = path.join(dir, rel);
    mkdirSync(path.dirname(dest), { recursive: true });
    writeFileSync(dest, contents);
  }
  if (!binary) return;
}

const { files, publicFiles } = build();
if (CHECK) {
  const scratch = mkdtempSync(path.join(tmpdir(), 'arch-port-'));
  try {
    writeTree(path.join(scratch, 'app'), files);
    writeTree(path.join(scratch, 'public'), publicFiles);
    execFileSync('diff', ['-rq', path.join(scratch, 'app'), OUT], { stdio: 'inherit' });
    execFileSync('diff', ['-rq', path.join(scratch, 'public'), PUBLIC], { stdio: 'inherit' });
  } catch (error) {
    if (error.status) process.exit(error.status);
    throw error;
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
  console.log(`port.mjs: ${files.size} app files and ${publicFiles.size} public files match`);
} else {
  writeTree(OUT, files);
  writeTree(PUBLIC, publicFiles);
  console.log(`port.mjs: wrote ${files.size} app files and ${publicFiles.size} public files`);
}
