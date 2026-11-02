// Integrated check of the NATIVE dashboard (one page, every agent a module), assembled build behind the emulated distribution, a seeded Cognito session.
//   node infra/emulate.mjs --port 5470 --api proxy      (after scripts/assemble.sh; proxy = the agents' LIVE APIs: this check only does GETs)
//   [AXE=1] node scripts/browser-check/native-check.mjs http://127.0.0.1:5470 <outPrefix> [1440x900|1024x768]
// usage: node native-check.mjs <baseUrl> <outPrefix> [WxH]   READ-ONLY: it signs in with a seeded session, switches agent, clicks navigation only. It never clicks a page's own buttons.
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

import { launch } from './cdp-lib.mjs';

// axe-core is a (transitive) dependency of the project: AXE=1 runs it on every page after the loading skeletons have gone.
const AXE_SRC = process.env.AXE ? readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8') : null;

const [, , base, outPrefix, size = '1440x900'] = process.argv;
const [W, H] = size.split('x').map(Number);
const CLIENT = 'al2kujlhvm530k6rud25c26mj';
const USER = 'priya.nair@example.com';
const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
const jwt = (p) => `${b64({ alg: 'none', typ: 'JWT' })}.${b64(p)}.sig`;
const now = Math.floor(Date.now() / 1000);
const common = { iss: 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_0cYHkw99D', sub: 'abc-123', iat: now - 60, exp: now + 3600, client_id: CLIENT };
const seed = `(() => { try { const p = 'CognitoIdentityServiceProvider.${CLIENT}'; const s = window.sessionStorage;
  if (!s.getItem(p + '.LastAuthUser')) {
    s.setItem(p + '.LastAuthUser', '${USER}');
    s.setItem(p + '.${USER}.idToken', '${jwt({ ...common, token_use: 'id', email: USER, given_name: 'Priya', family_name: 'Nair', 'cognito:username': USER })}');
    s.setItem(p + '.${USER}.accessToken', '${jwt({ ...common, token_use: 'access', username: USER })}');
    s.setItem(p + '.${USER}.refreshToken', 'refresh'); s.setItem(p + '.${USER}.clockDrift', '0'); } } catch (e) {}
  window.__msp = { errors: [], csp: [] };
  window.addEventListener('error', (e) => window.__msp.errors.push('error: ' + e.message));
  window.addEventListener('unhandledrejection', (e) => window.__msp.errors.push('rejection: ' + String((e.reason && e.reason.message) || e.reason)));
  document.addEventListener('securitypolicyviolation', (e) => window.__msp.csp.push(e.violatedDirective + ' ' + e.blockedURI));
  const ce = console.error; console.error = function () { window.__msp.errors.push('console.error: ' + [].slice.call(arguments).map(String).join(' ').slice(0, 240)); return ce.apply(console, arguments); };
})()`;

const ORDER = ['Onboarding', 'DevOps', 'SRE', 'WAFR', 'SecOps', 'Backup and DR'];
const results = [];
const check = (name, ok, extra = '') => { results.push({ name, ok }); console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${extra ? '  ' + extra : ''}`); };

// the dashboard's own chrome (everything in the sidebar that is not the agent's navigation), as a string of computed styles
const chromeFp = `(() => { const props = ['color','backgroundColor','fontSize','fontFamily','fontWeight','lineHeight','paddingTop','paddingLeft','marginTop','borderTopWidth','borderTopColor','borderRadius','display','width','height','boxShadow'];
  const els = [...document.querySelectorAll('aside *')].filter((e) => !e.closest('[role=group]') && !e.closest('[role=status]'));
  return els.map((e) => { const cs = getComputedStyle(e); return e.tagName + ':' + props.map((p) => cs[p]).join('|'); }).join('\\n'); })()`;
const mainInfo = `(() => { const m = document.querySelector('main'); return { len: m ? m.innerText.length : -1, h1: m && m.querySelector('h1') ? m.querySelector('h1').innerText.slice(0, 60) : '', head: m ? m.innerText.replace(/\\s+/g, ' ').slice(0, 110) : '', overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  skeleton: !!document.querySelector('main [role=status][aria-busy=true], [aria-label="Loading the navigation"]'), title: document.title }; })()`;
const api = `(() => performance.getEntriesByType('resource').filter((r) => r.name.includes('/agents/') && r.name.includes('/api')).map((r) => ({ n: r.name.replace(location.origin, '').slice(0, 90), s: r.responseStatus })))()`;

const c = await launch({ out: outPrefix, width: W, height: H, watchdogMs: 420000 });
try {
  await c.send('Page.enable'); await c.send('Page.addScriptToEvaluateOnNewDocument', { source: seed });
  await c.send('Page.navigate', { url: `${base}/` });
  await c.waitFor(`!!document.querySelector('aside button[aria-current]')`, 40, 'first agent opens');
  await c.sleep(1500);
  const fp0 = await c.ev(chromeFp);
  check('opens on the first agent, one sidebar', (await c.ev(`document.querySelectorAll('aside').length`)) === 1);
  check('no second sidebar or frame', (await c.ev(`document.querySelectorAll('iframe').length`)) === 0);

  const navLabels = () => c.ev(`[...document.querySelectorAll('aside [role=group] button')].map((b) => b.innerText.trim().split('\\n')[0])`);
  const sidebarName = () => c.ev(`(document.querySelector('aside')?.innerText || '').slice(0, 200)`);
  const openSwitcher = async () => {
    await c.ev(`document.querySelector('aside button[aria-label^="Switch agent"]').click()`);
    await c.waitFor(`!!document.querySelector('[role=dialog][aria-label="Switch agent"], [aria-label="Switch agent"][data-state=open]')`, 6, 'switcher opens');
  };
  const choose = (name) => c.ev(`(() => { const b = [...document.querySelectorAll('[aria-label="Switch agent"] li > button')].find((x) => x.innerText.includes(${JSON.stringify(name)})); if (!b) return false; b.click(); return true; })()`);
  const settle = async (name) => {
    for (let i = 0; i < 80; i++) {
      const [side, info] = [await sidebarName(), await c.ev(mainInfo)];
      if (side.toLowerCase().includes(name.toLowerCase()) && !info.skeleton && info.len > 80) return info;
      await c.sleep(250);
    }
    return await c.ev(mainInfo);
  };

  for (const [index, name] of ORDER.entries()) {
    const tag = `[${name}]`;
    if (index > 0) {
      await openSwitcher();
      const ok = await choose(name);
      check(`${tag} listed in Switch agent`, ok);
      if (!ok) continue;
    }
    const info = await settle(name);
    check(`${tag} the sidebar names the agent and the page rendered`, info.len > 80 && !info.skeleton, `main=${info.len} chars: "${info.head}"`);
    check(`${tag} address did not change`, (await c.ev(`location.pathname + location.search + location.hash`)) === '/');
    check(`${tag} no horizontal overflow`, info.overflowX <= 0, `overflowX=${info.overflowX}`);
    await c.shot(`${name}-first`);
    const labels = await navLabels();
    console.log(`  ${tag} nav: ${labels.join(' | ')}`);
    for (const label of labels) {
      await c.ev(`(() => { const b = [...document.querySelectorAll('aside [role=group] button')].find((x) => x.innerText.trim().split('\\n')[0] === ${JSON.stringify(label)}); b && b.click(); })()`);
      await c.sleep(1800);
      const page = await c.ev(mainInfo);
      const active = await c.ev(`document.querySelector('aside [aria-current=page]')?.innerText.trim().split('\\n')[0] || ''`);
      const crumb = await c.ev(`(document.querySelector('nav[aria-label="Breadcrumb"], header nav')?.innerText || '').replace(/\\s+/g, ' ')`);
      check(`${tag} ${label}: renders and is the active item`, page.len > 40 && active === label, `main=${page.len} active="${active}" h1="${page.h1}" crumb="${crumb}"`);
      await c.shot(`${name}-${label.replace(/[^a-z0-9]+/gi, '_').slice(0, 24)}`);
      if (AXE_SRC) {
        await c.waitFor(`!document.querySelector('main .skeleton-text, main .skeleton-block, main [role=status][aria-busy=true]')`, 14, 'skeletons gone'); // a loading placeholder is transient text on a grey bar
        await c.sleep(900); // axe reads colours mid-fade: let the entrance finish first
        await c.ev(AXE_SRC);
        const found = JSON.parse(await c.ev(`axe.run(document, { resultTypes: ['violations'] }).then((r) => JSON.stringify(r.violations.map((v) => ({ id: v.id, impact: v.impact, n: v.nodes.length, t: v.nodes.slice(0, 2).map((x) => x.target.join(' ').slice(0, 90)) }))))`));
        check(`${tag} ${label}: axe has no violation`, found.length === 0, found.map((v) => `${v.id}(${v.n}) ${v.t.join(' ; ')}`).join(' || '));
      }
    }
    const requests = await c.ev(api);
    const bad = requests.filter((r) => r.s >= 400 || r.s === 0);
    console.log(`  ${tag} API calls so far: ${requests.length}, not ok: ${JSON.stringify(bad.slice(0, 6))}`);
  }

  // SecOps Start once loaded (the checks above only waited for the skeleton): the new live-findings filters, then a look at the Pen test tab
  await openSwitcher(); await choose('SecOps'); await settle('SecOps');
  await c.ev(`[...document.querySelectorAll('aside [role=group] button')].find((x) => x.innerText.includes('1. Start')).click()`);
  const t0 = Date.now();
  const loaded = await c.waitFor(`document.querySelector('main')?.innerText.includes('Run settings')`, 25, 'SecOps Start loads');
  check('[SecOps] Start finishes loading with the live API', loaded, `${Date.now() - t0} ms after the click`);
  await c.sleep(1000); await c.shot('SecOps-start-loaded');
  await c.ev(`[...document.querySelectorAll('main label')].find((x) => x.innerText.includes('Read live findings'))?.click()`);
  await c.sleep(900);
  check('[SecOps] ticking "Read live findings" opens the filters (no request is sent)', await c.ev(`!!document.querySelector('[role=group][aria-label="Live findings filters"]')`));
  await c.shot('SecOps-start-filters');
  await c.ev(`[...document.querySelectorAll('aside [role=group] button')].find((x) => x.innerText.includes('3. Pen test')).click()`);
  await c.waitFor(`/Run a pen test|turned off|Checking whether/.test(document.querySelector('main')?.innerText || '')`, 20, 'SecOps pen test panel');
  await c.sleep(1500); await c.shot('SecOps-pentest-panel');
  console.log('  [SecOps] pen test panel: ' + (await c.ev(`document.querySelector('main')?.innerText.replace(/\\s+/g, ' ').slice(0, 200)`)));

  // back to the first agent: the dashboard's own chrome must look exactly as before (no CSS of any agent reached it)
  await openSwitcher(); await choose('Onboarding'); await settle('Onboarding'); await c.sleep(800);
  const fp1 = await c.ev(chromeFp);
  check('LEAK: the dashboard chrome (sidebar frame, Switch agent, account card) is identical after opening all five agents', fp0 === fp1, fp0 === fp1 ? '' : `before ${fp0.length} chars, after ${fp1.length}`);

  const state = await c.ev(`JSON.stringify(window.__msp)`);
  const msp = JSON.parse(state);
  check('no console errors / unhandled errors in the whole session', msp.errors.length === 0, JSON.stringify(msp.errors.slice(0, 5)));
  check('no Content-Security-Policy violation in the whole session', msp.csp.length === 0, JSON.stringify(msp.csp.slice(0, 5)));
  const all = await c.ev(api);
  const prefixes = new Set(all.map((r) => r.n.split('/api')[0]));
  check('every agent API call stayed on the dashboard origin under /agents/<id>/', all.every((r) => r.n.startsWith('/agents/')), [...prefixes].join(' '));
} finally { await c.finish(); }
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
for (const f of failed) console.log('FAILED:', f.name);
