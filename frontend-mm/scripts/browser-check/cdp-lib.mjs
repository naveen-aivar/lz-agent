import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync, rmSync } from 'node:fs';

export async function launch({ out, width = 1440, height = 1250, watchdogMs = 240000, extraArgs = [] }) {
  const PORT = 9300 + Math.floor(Math.random() * 500);
  const profile = `${out}-profile`;
  rmSync(profile, { recursive: true, force: true });
  mkdirSync(profile, { recursive: true });
  const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', '--hide-scrollbars', `--window-size=${width},${height}`, `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, ...extraArgs, 'about:blank'], { stdio: 'ignore' });
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const wd = setTimeout(() => { console.log('WATCHDOG'); try { ws.send(JSON.stringify({ id: 99999, method: 'Browser.close' })); } catch {} chrome.kill('SIGTERM'); setTimeout(() => { try { rmSync(profile, { recursive: true, force: true }); } catch {} process.exit(2); }, 1500); }, watchdogMs);
  let ws;
  for (let i = 0; i < 60; i++) { try { const l = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); const p = l.find((t) => t.type === 'page'); if (p) { ws = new WebSocket(p.webSocketDebuggerUrl); break; } } catch {} await sleep(500); }
  await new Promise((r) => (ws.onopen = r));
  let id = 0; const pend = new Map(); const errs = []; const listeners = new Map();
  ws.onmessage = (m) => { const g = JSON.parse(m.data); if (g.id && pend.has(g.id)) pend.get(g.id)(g); if (g.method && listeners.has(g.method)) listeners.get(g.method)(g.params); if (g.method === 'Runtime.exceptionThrown') errs.push(g.params.exceptionDetails?.exception?.description ?? 'exc'); if (g.method === 'Runtime.consoleAPICalled' && g.params.type === 'error') errs.push(g.params.args.map((a) => a.value ?? a.description).join(' ').slice(0, 300)); };
  const send = (method, params = {}) => new Promise((r) => { const my = ++id; pend.set(my, r); ws.send(JSON.stringify({ id: my, method, params })); });
  const ev = async (e) => (await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true })).result?.result?.value;
  const shot = async (n) => {
    let params = { format: 'png' };
    if (process.env.FULL) { const h = await ev('Math.min(document.documentElement.scrollHeight, 3200)'); const w = await ev('document.documentElement.clientWidth'); params = { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: w, height: h, scale: 1 } }; }
    const r = await send('Page.captureScreenshot', params); writeFileSync(`${out}-${n}.png`, Buffer.from(r.data ?? r.result.data, 'base64')); console.log('shot', n); };
  const waitFor = async (e, s, l) => { for (let i = 0; i < s * 4; i++) { if (await ev(e)) return true; await sleep(250); } console.log('TIMEOUT', l ?? e); return false; };
  const has = (t) => `document.body.innerText.includes(${JSON.stringify(t)})`;
  const click = (t, tag = 'button') => ev(`(()=>{const el=[...document.querySelectorAll('${tag}')].find(b=>b.textContent.trim().includes(${JSON.stringify(t)})&&!b.disabled);if(!el)return false;el.click();return true})()`);
  const mouseClick = async (x, y) => { await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y }); await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 }); await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 }); };
  const rectOf = (t, tag = 'button') => ev(`(()=>{const el=[...document.querySelectorAll('${tag}')].find(b=>b.textContent.trim().includes(${JSON.stringify(t)}));if(!el)return null;const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  const realClick = async (t, tag = 'button') => { const r = await rectOf(t, tag); if (!r) return false; await mouseClick(r.x, r.y); return true; };
  // The Chrome profile is a few hundred MB per run: remove it when the run ends (a full disk once stopped every command).
  const finish = async () => { clearTimeout(wd); try { ws.send(JSON.stringify({ id: 99998, method: 'Browser.close' })); } catch {} await new Promise((r) => setTimeout(r, 800)); try { ws.close(); } catch {} chrome.kill('SIGTERM'); await new Promise((r) => setTimeout(r, 1200)); try { rmSync(profile, { recursive: true, force: true }); } catch {} };
  await send('Page.enable'); await send('Runtime.enable');
  const on = (method, fn) => listeners.set(method, fn);
  return { on, send, ev, shot, waitFor, has, click, realClick, mouseClick, rectOf, errs, sleep, finish };
}
