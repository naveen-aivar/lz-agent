# Agent builders (contract)

The MSP dashboard (`frontend-msp/`) is ONE web origin. It shows the five MSP agents inside itself, one at a time, in an iframe that is
**same-origin**: `/agents/<id>/`. Same origin is what gives ONE login: every agent already signs in with the shared Cognito pool
(`us-east-1_0cYHkw99D`, public client `al2kujlhvm530k6rud25c26mj`, `amazon-cognito-identity-js`, tokens in `window.sessionStorage`). The dashboard signs
the person in once; the embedded agent finds the same session in the same storage and its own sign-in gate opens by itself.

The isolated agents stay exactly as they are (their repos, their live sites). The dashboard serves a SECOND COPY of each agent's static build, built
for a sub-path, talking to the agent's existing live API through a same-origin proxy path.

| id | worktree (read only) | stack | entry URL in the dashboard |
|---|---|---|---|
| `secops` | `/Users/arunsharma/Desktop/Project/ingram-ai-msp-agents-secops/agents/secops-agent/frontend` | Next 15 static export | `/agents/secops/` |
| `wafr` | `/Users/arunsharma/Desktop/Project/ingram-ai-msp-agents-wafr/frontend` | Next 15 static export | `/agents/wafr/` |
| `sre` | `/Users/arunsharma/Desktop/Project/ingram-ai-msp-agents-sre/frontend_new` | Next 15 static export (pnpm) | `/agents/sre/console/` |
| `devops` | `/Users/arunsharma/Desktop/Project/ingram-ai-msp-agents-devops/app` | Vite 5 + React 18 | `/agents/devops/` |
| `onboarding` | `/Users/arunsharma/Desktop/Project/ingram-ai-msp-agents/ui` | Vite 8 + React 19 | `/agents/onboarding/` |

(Backup and DR is NOT included: its team is still working on it.)

## Domain and CORS (the user approved both)

- The dashboard will be served at `https://msp.aivar.app` (CloudFront alias with the wildcard ACM certificate `*.aivar.app` already issued in this account) and also on its
  own `*.cloudfront.net` name. DNS for `aivar.app` is managed outside this account, so a CNAME is created by hand.
- The user said: add CORS to an agent's AWS side IF NEEDED. With the same-origin proxy most agents need none. If the built app still calls another host directly from the browser
  (an S3 presigned upload, an API Gateway, a font host), put the exact change in `needsAws` (for example the full S3 CORS JSON with `https://msp.aivar.app` and the dashboard's
  CloudFront origin as AllowedOrigins; additive only, never `*` with credentials). The integrator reviews and applies it. Do NOT apply AWS changes yourself.

## What each builder delivers (`frontend-msp/agents/<id>/`)

1. `build.sh <outDir>`: builds the agent for base path `/agents/<id>` into `<outDir>` (absolute; emptied first) so that `<outDir>/index.html` (or the agent's entry
   page) is what a browser gets for `/agents/<id>/`. Idempotent, non-interactive, no network except the package manager if it is truly needed (node_modules are
   already installed in every worktree; do NOT run `npm install` in a worktree).
2. `<outDir>/.msp-build.json` (written by build.sh), exactly this shape:
   ```json
   {
     "id": "secops",
     "basePath": "/agents/secops",
     "entry": "/agents/secops/",
     "apiProxy": [ { "prefix": "/agents/secops/api/", "originDomain": "d3hw4gjr2u1j6z.cloudfront.net", "originPath": "/api/", "note": "why this origin" } ],
     "rewrites": [ { "match": "^/agents/wafr/profiles/[^/]+/?$", "to": "/agents/wafr/profiles/_/index.html", "note": "dynamic route placeholder page" } ],
     "scriptHashes": ["'sha256-...='"],
     "externalHosts": { "font-src": [], "img-src": [], "connect-src": [], "style-src": [] },
     "needsAws": [ "free text: anything outside the build that must change for this agent to work from the dashboard origin (e.g. an S3 CORS entry)" ],
     "notes": "anything the integrator must know"
   }
   ```
   `apiProxy`: every same-origin API path the built app calls, mapped to the agent's EXISTING live API origin (read the agent's own deploy script / infra / README to find it;
   prefer the agent's live CloudFront domain, which adds its own origin token, over a raw load balancer). The proxy strips `prefix` and sends `originPath` + the rest.
   `rewrites`: dynamic routes / directory index rules a static host needs (S3 does not serve `index.html` for a directory by itself: the integrator's CloudFront
   Function adds `index.html` to any path ending in `/`, so only list rules BEYOND that).
   `scriptHashes`: the SHA-256 of every inline `<script>` in every HTML file of the build (CSP allows no inline script except these).
3. `<outDir>/msp-embed.css`: CSS the dashboard injects into the agent's iframe document. It must hide what the dashboard already provides: the agent's own
   signed-in person card / avatar / Sign out (the dashboard has the one avatar and the one Sign out), and nothing else. Verify the selectors in the built app.
4. `NOTES.md` in `frontend-msp/agents/<id>/`: how it works, what you patched and why, the base-path traps you met, how to rebuild, what is NOT verified.

## Rules (hard)

- **Never modify, stash, commit or leave changes in any agent repo or worktree.** Build from a scratch copy: `rsync -a --exclude node_modules --exclude .next --exclude out --exclude dist --exclude .git <app dir>/ <scratch>/app/`,
  then `ln -s <app dir>/node_modules <scratch>/app/node_modules` (if the toolchain refuses the symlink, patch in place TEMPORARILY with a trap that always restores
  and prove `git -C <worktree> status --porcelain` is identical before and after). Vite apps need no copy: `--base`, `--outDir <abs> --emptyOutDir` and env vars are enough.
  Put patches in `frontend-msp/agents/<id>/patches/` (small scripted edits or `.patch` files applied to the scratch copy), not in the repo.
- The scratch space is `/private/tmp/claude-502/-Users-arunsharma-Desktop-Project-ingram-agents-dashboard-frontend/527bed1d-31a6-44f3-851b-a87ff38c846e/scratchpad/msp/<id>/`.
  The disk is almost full (about 3 GB free): delete scratch copies, `.next` folders and Chrome profiles when you finish.
- Build WITH the shared sign-in (find the exact env var names in the agent's own deploy script, e.g. `scripts/deploy_*docext*.sh`; pool `us-east-1_0cYHkw99D`, client
  `al2kujlhvm530k6rud25c26mj`, region `us-east-1`, no custom endpoint).
- Same-origin API: set the agent's API base (env or config) so every call goes to `/agents/<id>/api/...`; no absolute URL to another host may remain in the built output
  (grep the output for `https://` and justify each hit). If the agent calls other hosts directly (e.g. S3 presigned uploads), list them in `externalHosts` and `needsAws`.
- Base path is the classic trap: `basePath` does not rewrite plain `<img src="/x">`, CSS `url(/x)`, `<script src="/x">`, `public/` files, `fetch('/x')`, service workers, manifest or
  favicon links. Find every root-relative URL in the built output (`grep -R '"/' ...`, CSS `url(`) and fix it in the scratch copy.
- Do not start real agent runs and never call anything that spends money or changes AWS. GET requests to the live sites/APIs are fine to learn their shape. AWS CLI read-only calls
  (profile `arun-doc-ex`) are fine; no AWS write calls.
- Test in a real browser (headless Chrome via `/private/tmp/claude-502/-Users-arunsharma-Desktop-Project-ingram-agents-dashboard-frontend/527bed1d-31a6-44f3-851b-a87ff38c846e/scratchpad/cdp-lib.mjs`;
  read the harnesses next to it for the pattern: `secops-harness/`, `wafr-harness/`, `sre-harness/` have fake APIs, `static-server.mjs` that emulates CloudFront, and a way to fake a signed-in session by
  seeding the Cognito SDK keys in sessionStorage before the page loads; use `AXE=1` style checks with `axe/node_modules/axe-core/axe.min.js`; JPEG screenshots; desktop widths only, do NOT test phone).
  Serve `<outDir>` the way CloudFront+S3 will (the path prefix `/agents/<id>/`, directory index, your `rewrites`), seed a signed-in session, load the entry URL, and show: the app renders, zero failed
  requests for assets, zero console errors, API calls go to `/agents/<id>/api/...` (a tiny fake API or stub is fine), no horizontal overflow at 1440x900 and 1024x768, axe has no new violations vs the
  isolated app. Then check the same page INSIDE an iframe of a same-origin parent page (`<iframe src="/agents/<id>/">`), with `msp-embed.css` injected.
- Ports: use only your own: secops 5410/8810, wafr 5420/8820, sre 5430/8830, devops 5440/8840, onboarding 5450/8850, infra 5470. Never touch ports 5173, 3125, 3000 (the user's dev servers).
- No AI attribution anywhere. Do not commit; the integrator commits.

## Report (final message, under about 80 lines)

What you built (paths), the exact `build.sh` usage and how long it takes, the `.msp-build.json` you produce (paste it), the API proxy mapping and how you learned it, every base-path trap and
what fixed it, what you verified in the browser (screens, widths, counts of failed requests / console errors / axe), what you could NOT verify, and anything in `needsAws`.
