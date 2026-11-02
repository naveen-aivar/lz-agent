#!/usr/bin/env node
// Runs the dashboard locally with each agent's API calls sent where YOU say: a stub, a fake, or the agent's live API.
//
//   node scripts/dev-proxy.mjs --port 5580 --app http://127.0.0.1:5560 \
//        --tco http://127.0.0.1:8810 --seven-rs http://127.0.0.1:8820 ...
//
// The dashboard (npm run dev, or any server of the built site) is --app. The browser talks only to --port: a path /agents/<id>/api/... is sent to
// the --<id> address with "/agents/<id>" taken off (so /agents/tco/api/runs reaches <tco>/api/runs, the same path the live API has), everything
// else goes to --app (the dev server's hot-reload socket included). An agent with no address answers 502 and says so. Never point a write at a live API
// unless you mean it.
import http from 'node:http';
import https from 'node:https';

const args = process.argv.slice(2);
const option = (name, fallback) => (args.includes(`--${name}`) ? args[args.indexOf(`--${name}`) + 1] : fallback);
const port = Number(option('port', '5580'));
const app = new URL(option('app', 'http://127.0.0.1:5560'));
const IDS = ['cva-output', 'seven-rs', 'mra', 'architecture-design', 'tco', 'landing-zone', 'migration-launch'];
const targets = Object.fromEntries(IDS.filter((id) => option(id)).map((id) => [id, new URL(option(id))]));

function forward(req, res, target, path) {
  const lib = target.protocol === 'https:' ? https : http;
  const headers = { ...req.headers, host: target.host };
  const upstream = lib.request({ hostname: target.hostname, port: target.port || (target.protocol === 'https:' ? 443 : 80), method: req.method, path, headers }, (answer) => {
    res.writeHead(answer.statusCode ?? 502, answer.headers);
    answer.pipe(res);
  });
  upstream.on('error', (error) => {
    res.writeHead(502, { 'content-type': 'text/plain' });
    res.end(`dev-proxy: ${target.host} did not answer (${error.code ?? error.message})`);
  });
  req.pipe(upstream);
}

const server = http.createServer((req, res) => {
  const match = /^\/agents\/([a-z][a-z0-9]*(?:-[a-z0-9]+)*)(\/api\/.*)$/.exec(req.url ?? '');
  if (match) {
    const target = targets[match[1]];
    if (!target) {
      res.writeHead(502, { 'content-type': 'text/plain' });
      res.end(`dev-proxy: no --${match[1]} address was given`);
      return;
    }
    return forward(req, res, target, match[2]);
  }
  return forward(req, res, app, req.url ?? '/');
});
server.on('upgrade', (req, socket, head) => {
  // The browser closing the hot-reload socket must not take the proxy down (EPIPE on the other half of the pipe).
  socket.on('error', () => {});
  const upstream = http.request({ hostname: app.hostname, port: app.port, method: req.method, path: req.url, headers: req.headers });
  upstream.on('upgrade', (answer, upSocket, upHead) => {
    socket.write(`HTTP/1.1 101 Switching Protocols\r\n${Object.entries(answer.headers).map(([k, v]) => `${k}: ${v}`).join('\r\n')}\r\n\r\n`);
    if (upHead?.length) socket.write(upHead);
    upSocket.on('error', () => socket.destroy());
    socket.on('close', () => upSocket.destroy());
    upSocket.pipe(socket).pipe(upSocket);
  });
  upstream.on('error', () => socket.destroy());
  upstream.end(head);
});
server.listen(port, '127.0.0.1', () => console.log(`dev-proxy on http://127.0.0.1:${port} -> app ${app.origin}; apis: ${Object.entries(targets).map(([id, t]) => `${id}=${t.origin}`).join(' ') || 'none'}`));
