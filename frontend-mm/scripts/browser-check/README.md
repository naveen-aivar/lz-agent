# Browser checks (headless Chrome, no extra packages)

`native-check.mjs` walks the whole assembled dashboard: every agent (switch through "Switch agent"), every navigation item, a seeded signed-in session,
the dashboard's own sidebar/top bar compared before and after all agents were opened (CSS-leak check), console errors, Content-Security-Policy
violations, where every API call went, and (with `AXE=1`) axe on every page once the loading skeletons have gone.

```bash
SHELL_BUILD_CMD=scripts/locked-build.sh scripts/assemble.sh           # build + assemble .build/site (a few minutes, needs ~1.5 GB of disk while building)
node infra/emulate.mjs --port 5470 --api proxy &                        # the real router + CSP functions; proxy = the agents' LIVE APIs (this check only reads)
AXE=1 node scripts/browser-check/native-check.mjs http://127.0.0.1:5470 /tmp/msp-check 1440x900
AXE=1 node scripts/browser-check/native-check.mjs http://127.0.0.1:5470 /tmp/msp-check 1024x768
kill <emulator pid>                                                     # by PID (pkill by name is refused in this environment)
```

It only clicks navigation: it never presses a page's own buttons (the DevOps and SecOps agents have real, billed actions). Last result on the five-agent
build: 67/67 at both widths. `cdp-lib.mjs` closes Chrome with `Browser.close` (a SIGKILLed Chrome leaves a multi-GB code-sign copy in /private/var/folders).
Per-agent fake APIs and checks live in `agents/<id>/harness/`.
