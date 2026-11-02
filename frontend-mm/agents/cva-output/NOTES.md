# CVA Output Processing in the dashboard

Source: `shubham-aivar/cva-output-agent`, the page in `cva/ui/static/index.html`. There is no `UI-ALIGNMENT.txt` in that repo. The isolated repository is not changed. The screens here are written for the dashboard.

What is kept: a new run (estate file, optional licensing and notes), the run list, overview, AWS Transform (connection check, start, approve, suggest, fetch, import), workloads, licensing, exceptions, agent proposals, review and release, outputs, and the audit.

What changed for the dashboard: no second sign-in and no left rail. The sections are steps. While a package is being built, three sheets slide into a folder. That is the only loop, and it stops when the person asks for less motion.

API: `/agents/cva-output/api/...` goes to the CVA key gate (`infra/key_gates.py`, `ingram-mm-dashboard-cva-output-key-gate`), which checks the signed-in person's Cognito ID token, adds `X-Access-Key` from Secrets Manager `ingram-mm-dashboard/cva-output-access-key` and calls `https://d2f11is2hu6tzu.cloudfront.net/api/...`: the agent's access-key deployment (stack `cva-agent-key` in the aivar-vision account 604775478403, `deploy/key/` in the agent's repo), set up on 2026-10-30 while its owner was away. It replaced the sign-in demo at `d23vbh52q1nk0h.cloudfront.net`, whose own session the dashboard could not pass. The key in this account is a copy of the agent account's `cva-agent-key/access-key`; rotate both together (`deploy/key/deploy.sh copy-key`). Finalising a run also sends its AWS Transform files to the central output store (the deck orchestrator's `cva.*` slots).

Limits: the instance is stopped every night at 15:30 UTC by that account's off-hours policy; until someone starts it (`deploy/key/deploy.sh start`) the screens show errors. Through the gate, calls longer than about 20 seconds return 502 even though the agent finishes them, and bodies over about 6 MB fail (uploads arrive as base64, so files over about 4.4 MB). Downloads under `/download/` are not proxied; the Outputs step lists the names.

Not verified against the live service: an upload or a real assessment. The pages were checked in headless Chrome at 1440x900 and 1024x768 against a local stand-in.
