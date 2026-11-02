# Architecture Design in the dashboard

Source: `aivar-tech/architecture-design-agent`, branch `feature/ui-ingram-align`, folder `deployment/ui-app`.
The isolated repository is not changed. `node agents/architecture-design/port.mjs --source <ui-app> --check` rebuilds `src/features/architecture-design/app/` and compares it.

The dashboard draws the sidebar, the top bar and the one toaster. The agent's own sidebar and top bar are left out. Dialogs and the searchable list are drawn into `#mm-architecture-design-portal` so their styles stay inside `.mm-architecture-design`.

API: `/agents/architecture-design/api/...` proxies to the HTTP API of the agent team's `a05-arch-dev` stack (`xtyojvbhm9.execute-api.us-east-1.amazonaws.com`, account 455162169375), switched from `ingram-architecture` (`6z8b7f8w27`) on 2026-10-30. Every route needs the shared `X-Access-Key`. The browser never holds it: CloudFront sends the calls to the Architecture Design key gate (`infra/key_gates.py`), which checks the signed-in person's Cognito ID token, adds the key from Secrets Manager `a05-arch-dev/access-key` (the agent stack's own secret) and calls `/dev/<path>` (the API's `dev` stage). The screens send the ID token (`port.mjs` edits `api.js`); a 401 says "Sign in again", there is no key prompt.

Updating: the agent team owns this folder. After a change to `deployment/ui-app`, run `node agents/architecture-design/port.mjs --source <ui-app>`, then `scripts/assemble.sh` and `DOMAIN_NAME=mm.aivar.app scripts/deploy.sh` (dry run, then `APPLY=1`). `DOMAIN_NAME` must be set: left empty, the deploy removes the `mm.aivar.app` alias from the distribution.

Not verified in a browser in this pass: every run step, axe, and the two widths. The sample run's files are in `public/agents/architecture-design/`.
