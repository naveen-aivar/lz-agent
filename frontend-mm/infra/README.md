# MSP dashboard hosting and deploy tooling

One private S3 bucket behind one CloudFront distribution serves the whole MSP dashboard. The site is **one static export**: the shell
(`out/`) which also holds every agent's screens (each a code-split chunk of the one Next app, `src/features/<id>/`), plus the static
files of `public/agents/<id>/` (images, samples, icons; Next copies them to `out/agents/<id>/`). There are no per-agent builds. The only
thing that is agent-specific on the network is the API: `/agents/<id>/api/*` is proxied to that agent's own API. Same origin is what gives
the single sign-in (see `agents/README.md`). Account 455162169375, region us-east-1, stack `ingram-msp-dashboard`.

```
scripts/assemble.sh   validates agents/*/manifest.json, builds the dashboard (npm run build), assembles .build/site/ from out/, checks it, renders .build/template.json
scripts/deploy.sh     dry run by default; APPLY=1 creates/updates the resources, uploads, invalidates, smoke-tests
infra/render.py       agents/<id>/manifest.json + out/.msp-build.json -> template.json, router.js, headers.js, summary.txt, smoke.txt
infra/direct.py       the same template deployed with S3/CloudFront API calls instead of CloudFormation (the SSO role may not use CloudFormation)
infra/emulate.mjs     local stand-in for the distribution (port 5470) to look at .build/site in a browser
infra/agents.txt      the agent ids (the one list to edit to add an agent)
infra/functions/      router.template.js (viewer-request) and headers.template.js (viewer-response)
infra/msp_render/     the Python package behind render.py (validation, template, CSP, site checks)
infra/test_*.py, infra/test_scripts.sh, infra/fixtures/   the tests and their fixtures
```

Typical run (nothing touches AWS until the last step):

```bash
SHELL_BUILD_CMD=scripts/locked-build.sh scripts/assemble.sh   # validate, build, check, render (a few minutes); plain `scripts/assemble.sh` runs `npm run build`
node infra/emulate.mjs                                        # optional: look at it at http://127.0.0.1:5470/ first
scripts/deploy.sh                                             # DRY RUN: account guard, validate, plan, file counts; changes nothing
APPLY=1 scripts/deploy.sh                                     # do it; ends by printing the CNAME to create
```

`scripts/locked-build.sh` takes turns with other builds on a busy machine and removes `.next` afterwards; a plain `npm run build` leaves `.next` (over 1 GB) behind.

## Where each piece comes from

| Input | Written by | Used for |
|---|---|---|
| `agents/<id>/manifest.json` | the agent's porter | `apiProxy` (prefix `/agents/<id>/api/`, `originDomain`, `originPath`) -> router rules, API origins and behaviours; `externalHosts` -> the CSP; `needsAws` and `note` -> summary.txt |
| `out/.msp-build.json` | `scripts/export-hashes.mjs` (part of `npm run build`) | the SHA-256 of every inline script of the dashboard's pages -> `script-src` |
| `infra/agents.txt` | by hand | which manifests exist; render.py refuses a manifest that is not listed and a listed id without one |

## How a request is served

| Request | What happens |
|---|---|
| `/`, `/anything/without/a.dot` | default behaviour -> router rewrites to `/index.html` (the dashboard is one page; there is no URL routing inside it) |
| `/agents`, `/agents/` | no agent named: the dashboard |
| `/agents/<id>/api/...` | its own cache behaviour -> custom HTTPS origin; router swaps `prefix` for `originPath` (`/agents/secops/api/runs/1` -> `/api/runs/1`); a `.` or `..` segment (also `%2e`) answers 400 so a path can never climb out of `originPath` |
| `/agents/<id>/<anything else>` | **a static file of the site**: S3 gets the path as it is (`/agents/sre/img/topology.svg`). Nothing is rewritten and no `index.html` is added, so `/agents/sre/`, `/agents/sre/console` and a missing file are a real 404 (S3's `NoSuchKey`), never the dashboard |
| a path whose last segment has a dot | a file: served as is; a missing one is a real 404 (never the dashboard) |

The API behaviours: caching disabled (managed `CachingDisabled`), all seven HTTP methods, HTTPS only to the origin (TLS 1.2,
60 s read timeout), no cookies sent. One origin per distinct `originDomain` (devops and onboarding may share one); behaviours are
ordered longest prefix first because CloudFront takes the first match. A manifest prefix must be `/agents/<id>/api/` or a folder below it
(anything else would hide the agent's static files). Default behaviour: `redirect-to-https`, GET/HEAD, compression,
managed `CachingOptimized` (it honours the `Cache-Control` the upload sets), both functions.

Bucket: all public access blocked, SSE-S3, BucketOwnerEnforced, TLS-only, readable only by this distribution through an origin access
control (it may also `ListBucket`, which makes a missing file a 404 instead of a 403). Alias `msp.aivar.app` is the stack parameter
`DomainName` (empty = serve on the `*.cloudfront.net` name only; `CertificateArn` is the `*.aivar.app` ACM certificate), SNI, TLSv1.2_2021,
HTTP/2+3, `PriceClass_100`. No WAF, no standard logging. Everything is tagged `Project=ingram-msp-dashboard`.

### One Content-Security-Policy for the whole site

Every agent's screens run on the dashboard's own pages now, so there is one policy, set by the viewer-response function on every `text/html`
response (a response-headers policy may carry at most 1,783 characters of CSP; the hashes alone take about 55 characters each, so the policy comes from a function):

```
default-src 'self'; script-src 'self' <the dashboard build's inline-script hashes>; style-src 'self' 'unsafe-inline' <style-src hosts>;
img-src 'self' data: <img-src hosts>; font-src 'self' data: <font-src hosts>;
connect-src 'self' https://cognito-idp.us-east-1.amazonaws.com <connect-src hosts>;
frame-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
```

The hosts are the **union** of every agent's `externalHosts` (and the shell file's, if it ever has any), each once, sorted. A host one agent
declares is therefore allowed for every agent's screens: keep each manifest to what its screens really call. `script-src` has the hashes of
`out/.msp-build.json` and nothing else (no `unsafe-inline`, no `unsafe-eval`, no script host; `externalHosts` has no `script-src` key).
Nothing frames anything: `frame-ancestors 'none'` here and `X-Frame-Options: DENY` from the response-headers policy (which also carries HSTS
1 year, `nosniff`, `Referrer-Policy: strict-origin-when-cross-origin` and a `Permissions-Policy` that disables camera, microphone and
geolocation). If a screen ever needs to embed a frame (a PDF preview from a `blob:` URL, say), `frame-src` has to be opened for exactly that.

The function is about 1.4 KB with the real manifests (the limit of a CloudFront Function is 10 KB; render.py warns from 8,000 bytes and
refuses at 10,000, which is room for about 160 more inline-script hashes). The router is about 1.1 KB. Both are generated from data and the
generated code is what the tests run in Node. The comment lines are stripped so every byte counts.

### What render.py refuses (nothing is written then; every problem is listed at once)

A manifest whose `id` is not its folder, a missing `id`/`apiProxy`/`externalHosts`, a `scriptHashes` key (hashes belong to the one dashboard
build), non-empty `rewrites` (there are no per-agent routes), an `originDomain` that is not a bare lowercase DNS name (no scheme, port,
path, IP), a `prefix` outside `/agents/<id>/api/` (or with `.` / `..` segments, or not ending in `/`), an `originPath` that is not a plain absolute path
(empty means the origin's root), an `externalHosts` value that is not an `https://`/`wss://` host source (no path, quote, space, semicolon or comma; no `*.com`;
`data:` for fonts and images, `blob:` for images only) or an unknown key (script hosts are not allowed), a malformed script hash (must be `'sha256-<43 base64>='`),
a manifest folder that is not in `agents.txt` (or an id in it without a manifest), a function over 10 KB, a template over 51,200 bytes, more than 75 behaviours or 100 origins.
`--check-manifests` runs only the manifest part (assemble.sh does it before the build starts). `--check-site` additionally checks the assembled folder:
**every inline `<script>` of every HTML page has its SHA-256 in `scriptHashes`** (otherwise the page loads blank under the CSP), no script from another host,
`index.html` at the root, only known agent folders under `agents/`, no file under an API prefix (it could never be served), no `.msp-build.json`/`NOTES.md`/`.map`/`.DS_Store`,
no AWS key or private key.

### If the headers function outgrows 10 KB

The limit is fixed (a KeyValueStore would hold more, at the price of another resource). What grows the function is the number of distinct inline scripts of
the dashboard's pages (Next's bootstrap and flight data) and the hosts in the manifests. Before reaching for more machinery: fewer distinct inline scripts is
cheaper; hashes written as `~<base64>` and expanded in the function save 8 bytes each (the earlier version did this and it is a ten-line change in
`msp_render/functions.py` and `headers.template.js`).

## deploy.sh in detail

1. Account guard: only account 455162169375 (profile `arun-doc-ex`, or whatever `AWS_PROFILE` you set); this runs in the dry run too.
2. Dry run (default): re-renders and re-checks, reads what exists, prints the plan, the number of files per cache class
   and, for CloudFormation mode and an existing stack, what would change in it (resources and parameters), and **changes nothing**.
3. `APPLY=1`: creates or updates the resources (below); then, on a re-deploy, a **backup of the live bucket** to
   `.build/backup/<UTC time>/` before the first overwrite (it refuses if the disk cannot hold it); then the upload, **never with `--delete`**:
   the hashed files (`_next/static/*`; `public,max-age=31536000,immutable`) first, other files (`public,max-age=3600`; this includes the agents' static files,
   which keep their names) next, HTML/JSON/TXT (`no-cache`) last, so no page points at an asset that is not there yet; then an invalidation of `/*` and a wait.
4. Smoke checks through the distribution: `/` and a deep link answer 200 as HTML with the CSP (`frame-ancestors 'none'`, `script-src 'self'` without
   `unsafe-inline`/`unsafe-eval`, and the page's own first script hash, which proves the right policy reached the page), `X-Frame-Options: DENY`, `nosniff`,
   `Referrer-Policy`, `Permissions-Policy`, HSTS; the files the page refers to load; one hashed file is served with the right type and `immutable`; a missing
   file is a 404; for each agent that has files under `public/agents/<id>/`, one of them comes back as that file (200, not HTML) and a missing file under
   `/agents/<id>/` is a 404; each API proxy path is probed once and only reported (a 502/504 there means CloudFront cannot reach that origin).
   Any failure exits non-zero and says the new site is live and how to roll back.
5. Prints the DNS record. `aivar.app` is not hosted in this account, so by hand: `msp.aivar.app  CNAME  <dxxxx>.cloudfront.net`.

Two ways to create/update the resources, from the same `.build/template.json`:

* `DEPLOY_MODE=direct` (the default): `infra/direct.py` makes the S3 and CloudFront calls itself. It finds each resource by name, creates it if missing, updates it if it differs
  (the API's own defaults and its list order are not differences), never deletes. For a login that may not use CloudFormation.
* `DEPLOY_MODE=cfn`: `aws cloudformation deploy` of stack `ingram-msp-dashboard`.

infra/direct.py finds the live resources by their names (the distribution by its `Comment`, the two functions, the headers policy, the request policy, the access control):
those strings are pinned by `test_render.py` and `test_direct.py`; rewording one would make a direct deploy create a second copy next to the live one.

Settings (environment): `APPLY`, `DEPLOY_MODE`, `AWS_PROFILE`, `STACK_NAME`, `DOMAIN_NAME`, `CERTIFICATE_ARN`, `ROLLBACK_FROM`, `SMOKE_BASE_URL`.
A failure after the first change leaves the bucket half old, half new; the cure is to run the script again (every step is repeatable)
or to roll back.

## Moving from the first shape (separate agent builds in frames) to this one

The live site on 2026-10-28 still has the first shape: per-agent builds under `agents/<id>/`, a router with directory-index and rewrite rules, a CSP per path.
Deploying the new shape changes (read-only check: `DEPLOY_MODE=direct scripts/deploy.sh` lists each resource as "up to date" or "would update"; nothing is created):

* the two functions' code (router, headers): both are replaced; * the response-headers policy: `X-Frame-Options` `SAMEORIGIN` -> `DENY`;
* the distribution's API origins and behaviours become what the manifests say (the sixth agent, `backupdr`, adds its API Gateway origin and `/agents/backupdr/api/*`; an agent whose
  `originDomain` moved gets the new origin): the dry run's plan says "would update" for it, and `infra/direct.py plan` shows it before anything is sent;
* nothing else: the bucket and the access control stay as they are.

Things to know:

1. **Order inside one deploy.** The functions go live before the files are uploaded, so for the minute or so of the upload the new rules meet the old files (the old
   dashboard page has other script hashes than the new policy, so it is blank until its replacement is uploaded). The same was true before; the HTML goes last on purpose.
2. **The old per-agent files stay in the bucket** (the deploy never deletes): `agents/<id>/_next/`, `agents/<id>/assets/`, `agents/<id>/**/index.html`, `msp-embed.css`.
   The dashboard no longer refers to them and the router no longer adds `index.html` for them, but a request for an exact old file name is still served (with the new CSP,
   so an old page would be blank). Remove them once the new site is good. This is the one place `--delete` is wanted, limited to the `agents/` prefix and keeping the new static files:
   ```bash
   export AWS_PROFILE=arun-doc-ex AWS_DEFAULT_REGION=us-east-1
   B=ingram-msp-dashboard-455162169375-us-east-1
   SRC=.build/site/agents; [ -d "$SRC" ] || { mkdir -p .build/empty; SRC=.build/empty; }     # no static files at all: an empty folder
   aws s3 sync "$SRC" "s3://$B/agents" --delete --dryrun      # lists what would be removed and nothing else
   ```
   then the same without `--dryrun` (the deploy's own backup in `.build/backup/` holds the old files).
3. **Rolling back across this change needs the old functions, not only the old files.** `ROLLBACK_FROM=.build/backup/<time>` puts the old *files* back and leaves the stack alone, so with
   the new router the old agent pages are not served. To go all the way back, re-apply the old template: the last old-shape render is kept in `.build/old-shape/`
   (`template.json`, `router.js`, `headers.js`); `cp .build/old-shape/template.json .build/template.json && python3 infra/direct.py apply` restores the old functions and the `SAMEORIGIN` header
   (not run here), and then `ROLLBACK_FROM=... APPLY=1 scripts/deploy.sh` for the files. `.build/` is not in git: the copy only exists on this machine.

## Rollback

```bash
ls .build/backup/                                            # one folder per re-deploy (the site as it was before it)
ROLLBACK_FROM=.build/backup/20261027T101500Z scripts/deploy.sh               # dry run first
ROLLBACK_FROM=.build/backup/20261027T101500Z APPLY=1 scripts/deploy.sh      # re-uploads it with the right cache headers, invalidates, smoke-tests
```

A plain `aws s3 sync` of the backup is not enough: the backup carries no `Cache-Control`, and `sync` skips same-size files that look older.
The rollback leaves the stack alone and, like every deploy, also backs up what it replaces (so a rollback can be undone). Files that only the newer deploy
added stay in the bucket, unreferenced. To roll back the stack itself (a bad function, a bad behaviour), check out the previous
`agents/*/manifest.json` and `infra/` or fix the manifest, run `scripts/assemble.sh` and deploy: the template is generated, so a deploy is also the revert.
Backups pile up on a disk that is almost full: delete old ones by hand when the new site is good.

## Tear down

Remove the DNS record first (a CNAME left pointing at a deleted distribution is a takeover risk), then:

```bash
export AWS_PROFILE=arun-doc-ex AWS_DEFAULT_REGION=us-east-1
aws s3 rm s3://ingram-msp-dashboard-455162169375-us-east-1 --recursive      # CloudFormation cannot delete a non-empty bucket
aws cloudformation delete-stack --stack-name ingram-msp-dashboard
aws cloudformation wait stack-delete-complete --stack-name ingram-msp-dashboard
```

The bucket is not versioned, so emptying it is that one command. The distribution takes a few minutes to delete. (A site created with `DEPLOY_MODE=direct`
has no stack: delete the distribution, functions, policies and access control by hand, in that order, after disabling the distribution.)

## Key gates
An agent API that wants a shared access key (the TCO agent's, the deck orchestrator's, Architecture Design's and CVA Output's) is not called by the browser directly. CloudFront sends `/agents/<id>/api/...` to that agent's **key gate**, a Lambda function URL in this account. The gate checks the signed-in person's Cognito ID token (the dashboard's pool), reads the agent's access key from Secrets Manager (`ingram-mm-dashboard/<id>-access-key`), adds it as `X-Access-Key` and forwards the call. The browser never receives the key, and a call without a valid token gets 401 before the key is read.
* One code file serves every gate (`infra/key_gate/index.js`); `infra/key_gates.py` lists the gates (`Gate`: function, role, secret, the API's host) and gives each its settings as environment variables (`PREFIX`, `STAGE`, `UPSTREAM`, `SECRET_ID`, `LABEL`). With no environment the code is the TCO gate it was before. A gate is only built when the agent's API origin is in the distribution, that is, when the agent is in `infra/agents.txt`.
* `deploy.sh` creates or updates each wanted gate before the distribution. If an agent's secret is missing, the dry run says `BLOCKED` and an apply stops at that gate with a message, before it changes the distribution.
* Connecting the deck orchestrator (not done): (1) `scripts/copy-orchestrator-key.sh` (a dry run first; `APPLY=1` copies the key from `mm-dev/access-key` in account 831493647146 to `ingram-mm-dashboard/orchestrator-access-key` here, without printing it; it needs both SSO profiles logged in); (2) rename `agents/orchestrator/manifest.pending.json` to `manifest.json` and add `orchestrator` to `infra/agents.txt`; (3) add the dashboard origins to the CORS of bucket `mm-dev-data-831493647146` (see `needsAws` in the manifest); (4) `scripts/assemble.sh`, then a dry run and an apply of `deploy.sh` with `DOMAIN_NAME=mm.aivar.app` and the `NEXT_PUBLIC_COGNITO_*` ids set.
* The next apply after this change also updates the TCO gate's code (the file changed) and sets its environment. Its behaviour is the same; its 502 message now says "The service could not be reached."
* Tests: `python3 -m unittest test_direct`, `node --test infra/key_gate/index.test.mjs`.

## Adding an agent

1. Port its screens (`src/features/agents/PORTING.md`) and give it `agents/<id>/manifest.json`: `apiProxy` (`/agents/<id>/api/` -> origin), `externalHosts` (only what its screens call from the browser),
   `needsAws` (anything outside this repo that must change). Static files its screens load go in `public/agents/<id>/`.
2. Add `<id>` to `infra/agents.txt`. Nothing else is hand-edited: `scripts/assemble.sh` validates the manifest, `render.py` adds its API origin and behaviour to the router and the template and its hosts
   to the one policy, and the dry run lists what changed.
3. Optional: copy `infra/fixtures/agents/<a similar one>` to a fixture for it and add the id to `AGENT_IDS` in `infra/test_render.py` (and its API pattern to the lists
   in `test_render.py`/`test_direct.py` that name them). `infra/test_scripts.sh` takes its agents from the fixtures folder. `TestAgentList` fails until `agents.txt`, the real manifests and the fixtures agree.

A new agent adds one behaviour (and maybe one origin) to the distribution (limits: 75 and 100, checked by render.py). To remove one, take it out of `agents.txt`;
its files stay in the bucket (the deploy never deletes) until you remove `agents/<id>/` by hand.

## Tests

```bash
python3 -I -m unittest discover -s infra -p "test_*.py"    # render (template, both functions run in Node over a table of URIs, every refusal, site checks, the real manifests) and direct.py's translation
bash infra/test_scripts.sh                                  # assemble.sh and deploy.sh in both modes: dry run, first deploy, re-deploy, rollback, the shape change, smoke failures
node --test scripts/*.test.mjs                              # scope-css
```

None needs AWS access or the network. `test_scripts.sh` replaces the AWS CLI with a test double (`infra/fixtures/stubs/aws`; `aws_direct.py` keeps a pretend S3/CloudFront account for the direct mode)
and serves the smoke checks from `infra/emulate.mjs` (port 5470); it also checks that the cache class deploy.sh uploads for every file is the one the emulator serves.
`test_render.py` renders the repository's real `agents/*/manifest.json` too, so a manifest that does not pass shows up there.
Template checks: deploy.sh runs `aws cloudformation validate-template` itself in `DEPLOY_MODE=cfn`; `cfn-lint -c I,W,E .build/template.json` was clean on the first-shape template and is not installed here now.
The template's shape has not changed apart from `X-Frame-Options` and the function code.

## Decisions to review

* **No cookies to the agents' APIs.** The managed `AllViewerExceptHostHeader` origin request policy forwards all cookies. The template makes its own policy
  (`ingram-msp-dashboard-api-origin`): all headers except `Host`, all query strings, no cookies. To use the managed one instead (id `b689b0a8-53d0-40ab-baf2-68738e2966ac`), put that id in the API behaviours'
  `OriginRequestPolicyId` in `msp_render/template.py` and drop the `ApiOriginRequestPolicy` resource.
* **60 s origin read timeout** for the API origins (`API_READ_TIMEOUT_SECONDS`). A call that can run longer gets a 504; CloudFront's quota table lists 1 to 120 s.
* **`/agents/<id>/` is static files, full stop.** `/agents/sre/` or an old bookmark such as `/agents/sre/console/` answers 404 (S3 `NoSuchKey`), not the dashboard. `/agents` and `/agents/` (no agent named) go to the dashboard.
  If you prefer every extension-less path under `/agents/` to land on the dashboard, it is one line in `functions/router.template.js`.
* **One policy, so the union of hosts.** A host declared by one agent is allowed for all (see above).
* **No bucket versioning.** The rollback is the local backup; versioning would make the tear-down a long version-deleting job. `UpdateReplacePolicy: Retain` keeps the bucket if a template change ever replaced it.
* **`assemble.sh` deletes `out/`** before building, so a stale export can never be deployed.
* `HSTS` is sent with `includeSubDomains` and without `preload`.
* The distribution's `Comment` still reads "shell, agent UIs and API proxies": direct.py finds the distribution by it.

## Not verified here (nothing in AWS was created or changed)

* A real deploy of this shape (either mode), CloudFront's own runtime of the two functions (they were run in Node, in strict mode), the smoke checks against the real distribution
  (they ran against `infra/emulate.mjs`), `Content-Type` as S3 will store it for the agents' static files (the upload guesses it from the extension; unknown extensions become `application/octet-stream`).
* That `direct.py` applies the changed headers policy (`FrameOptions`) to the live policy: it is covered against the test double, which returns lists in another order and adds fields of its own,
  not against the real API. The live distribution, functions and policies were only read (`get-function`, `get-distribution-config`, `list-*`): same API origins and behaviours as the manifests, `SAMEORIGIN` today.
* The real dashboard build's pages under this CSP in a browser, with every agent's screens ported: only the shell stand-ins existed when this was written
  (`out/.msp-build.json`: 11 inline-script hashes; the policy is 985 characters).
