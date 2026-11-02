# frontend-mm: the Migration and Modernization dashboard

One static site for every Migration and Modernization agent: one sign-in, one sidebar with "Switch agent", and each agent's screens as a module of
this app. It is a copy of `frontend-msp/` (the MSP dashboard) with the MSP agents taken out; the shell, sign-in, design system, infra and scripts are
the same and work the same way.

## The agents

`src/features/agents/registry.ts` lists them, in the order a migration meets them:

| Id | Agent |
|---|---|
| `cva-output` | CVA Output Processing Agent |
| `seven-rs` | 7Rs Agent |
| `mra` | MRA Agent |
| `architecture-design` | Architecture Design Agent |
| `tco` | TCO Agent |
| `landing-zone` | Landing Zone Deployment Agent |
| `migration-launch` | Migration Launch Agent |

Connected: CVA Output Processing, MRA, Architecture Design and TCO. The other three open `src/features/not-connected/`, a page that says the agent is not connected and calls nothing. Taglines for the agents still waiting are placeholders until each team confirms what its agent does.

## Connecting an agent (when its team shares a working UI)

1. Bring its screens in as `src/features/<id>/` with a `module.tsx` (see `src/features/agents/PORTING.md`; it was written for the MSP agents and the
   rules are the same: no routing by address, `agentApiBase('<id>')` for every API call, plain CSS scoped under `.msp-<id>` with
   `scripts/scope-css.mjs`, the dashboard's one toaster, no second sidebar or sign-in).
2. Point the agent's `load` in `registry.ts` at that module.
3. Add the id to `infra/agents.txt` and write `agents/<id>/manifest.json` (its API origin, proxied at `/agents/<id>/api/`; the outside hosts its
   screens call). The agents' own backends are deployed in their own AWS accounts; only this site lives in doc-ex.

## Sign-in

The shared Cognito pool and its public app client (`.env.production`; the ids are not secrets), the same as the MSP dashboard and every agent: one
account works everywhere. The sign-in only gates the pages; the agents' APIs are protected (or not) by the agents themselves.

## Commands

```bash
npm run dev                      # http://localhost:5560
npm run typecheck && npm run lint && npx vitest run
python3 -I -m unittest discover -s infra -p "test_*.py" && bash infra/test_scripts.sh
SHELL_BUILD_CMD=scripts/locked-build.sh scripts/assemble.sh     # build + assemble .build/site
AWS_PROFILE=default scripts/deploy.sh                           # DRY RUN
AWS_PROFILE=default APPLY=1 scripts/deploy.sh                   # deploy
```

`node_modules` here may be hard-linked from `frontend-msp/node_modules` (no extra disk): do not run `npm install` in this folder until it has its own
copy, or it changes the MSP dashboard's packages too.

## Deployment (doc-ex 455162169375, us-east-1)

`scripts/deploy.sh` (see `infra/README.md`, written for the MSP dashboard; the steps are the same) creates its own resources, separate from the MSP
dashboard's: bucket `ingram-mm-dashboard-455162169375-us-east-1`, functions `ingram-mm-dashboard-router` / `-headers`, and a distribution found by
its comment "Ingram Migration and Modernization dashboard: shell, agent UIs and API proxies". No custom domain by default (the cloudfront.net name
only); for one, set `DOMAIN_NAME=mm.aivar.app` (the `*.aivar.app` certificate is the default `CERTIFICATE_ARN`) and create the CNAME where aivar.app
is managed.
