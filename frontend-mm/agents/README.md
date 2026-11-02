# agents/

One folder per agent the dashboard hosts. What is here now:

- `<id>/manifest.json` — how the dashboard reaches the agent's API: `apiProxy` (which live origin `/agents/<id>/api/...` is sent to, and with what path), `externalHosts` (other hosts the agent's screens call from the browser, for the Content-Security-Policy) and `needsAws` (anything outside this repo that must change for it, such as a CORS entry). `infra/` reads these.
- `<id>/port.mjs` — brings the agent's screens from the isolated agent's repository (read only) into `src/features/<id>/app/`, with scripted adaptations. Re-run it to pick up what the agent's team changed.
- `<id>/NOTES.md` — what was adapted and why, how to re-port, what is not verified.
- `<id>/embedded/` — the first version of the dashboard hosted each agent as a separate build in a frame; its build scripts, patches and test harnesses are kept here for reference only.

How an agent's screens become part of the dashboard: `src/features/agents/PORTING.md`.
