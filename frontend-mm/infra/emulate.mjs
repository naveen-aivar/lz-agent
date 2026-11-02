#!/usr/bin/env node
// A local stand-in for the CloudFront distribution, to look at the assembled site in a real browser before it is
// deployed, and to test scripts/deploy.sh's smoke checks without AWS.
//
//   node infra/emulate.mjs [--port 5470] [--site .build/site] [--api stub|proxy]
//
// It runs the REAL generated .build/router.js and .build/headers.js (the same code CloudFront will run), reads the
// API origins and the response headers from .build/template.json, and serves the files of .build/site with the
// content type and Cache-Control scripts/deploy.sh will upload (the dashboard, which holds every agent's screens, and the
// agents' static files under /agents/<id>/). API paths (/agents/<id>/api/...) answer with a JSON
// stub that shows where CloudFront would send them (--api stub, the default), or are forwarded to the agents' live
// APIs (--api proxy; those are real requests). What it cannot show: CloudFront's own caching, compression, HTTP/3,
// or S3's behaviour. HSTS is sent but browsers ignore it over http.
import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const infraDir = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const option = (name, fallback) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback);
const root = path.resolve(option('--root', path.join(infraDir, '..')));
const build = path.join(root, '.build');
const siteDir = path.resolve(option('--site', path.join(build, 'site')));
const port = Number(option('--port', '5470'));
const apiMode = option('--api', 'stub');
if (!['stub', 'proxy'].includes(apiMode)) throw new Error('--api must be stub or proxy');
for (const needed of [path.join(build, 'template.json'), path.join(siteDir, 'index.html')]) {
  if (!fs.existsSync(needed)) throw new Error(`${needed} is missing: run scripts/assemble.sh first`);
}

const loadFunction = (file) => {
  const context = vm.createContext({});
  vm.runInContext('"use strict";\n' + fs.readFileSync(file, 'utf8'), context);
  return vm.runInContext('handler', context);
};
const router = loadFunction(path.join(build, 'router.js'));
const headersFunction = loadFunction(path.join(build, 'headers.js'));

const template = JSON.parse(fs.readFileSync(path.join(build, 'template.json'), 'utf8'));
const distribution = template.Resources.Distribution.Properties.DistributionConfig;
const originDomain = Object.fromEntries(distribution.Origins.map((origin) => [origin.Id, origin.DomainName]));
const apiBehaviours = (distribution.CacheBehaviors || []).map((behaviour) => ({
  prefix: behaviour.PathPattern.replace(/\*$/, ''),
  domain: originDomain[behaviour.TargetOriginId],
}));

const policy = template.Resources.SecurityHeadersPolicy.Properties.ResponseHeadersPolicyConfig;
const security = policy.SecurityHeadersConfig;
const policyHeaders = {
  'strict-transport-security': `max-age=${security.StrictTransportSecurity.AccessControlMaxAgeSec}${security.StrictTransportSecurity.IncludeSubdomains ? '; includeSubDomains' : ''}`,
  'x-content-type-options': 'nosniff',
  'x-frame-options': security.FrameOptions.FrameOption,
  'referrer-policy': security.ReferrerPolicy.ReferrerPolicy,
};
for (const item of policy.CustomHeadersConfig.Items) policyHeaders[item.Header.toLowerCase()] = item.Value;

const TYPES = {
  html: 'text/html', js: 'text/javascript', mjs: 'text/javascript', css: 'text/css', json: 'application/json', txt: 'text/plain',
  svg: 'image/svg+xml', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif', ico: 'image/x-icon',
  woff2: 'font/woff2', woff: 'font/woff', webmanifest: 'application/manifest+json', xml: 'application/xml', wasm: 'application/wasm',
};
// The same three classes as scripts/deploy.sh: only Next's content-hashed files are immutable.
const IMMUTABLE = [/^_next\/static\//];
const cacheControl = (relative) => {
  if (IMMUTABLE.some((pattern) => pattern.test(relative))) return 'public,max-age=31536000,immutable';
  return /\.(html|json|txt)$/.test(relative) ? 'no-cache' : 'public,max-age=3600';
};

const viewerHeaders = (request) => Object.fromEntries(Object.entries(request.headers).map(([name, value]) => [name, { value: String(value) }]));
const flat = (headers) => Object.fromEntries(Object.entries(headers).map(([name, entry]) => [name, entry.value]));

function send(response, status, headers, body, method) {
  response.writeHead(status, { ...policyHeaders, ...headers });
  response.end(method === 'HEAD' ? undefined : body);
}

function serve(request, response) {
  const method = request.method;
  const url = new URL(request.url, 'http://localhost');
  const original = url.pathname;
  const viewerRequest = () => ({ method, uri: original, querystring: {}, headers: viewerHeaders(request) });
  const routed = router({ request: viewerRequest() });
  const log = (status, note = '') => console.log(`${method} ${original} -> ${status}${routed.uri && routed.uri !== original ? ` (as ${routed.uri})` : ''}${note}`);

  if (routed.statusCode) {
    log(routed.statusCode);
    return send(response, routed.statusCode, { 'content-type': 'text/plain' }, routed.statusDescription || '', method);
  }

  const api = apiBehaviours.find((behaviour) => original.startsWith(behaviour.prefix));
  if (api) {
    if (apiMode === 'stub') {
      log(200, ' [api stub]');
      return send(response, 200, { 'content-type': 'application/json', 'cache-control': 'no-store' },
        JSON.stringify({ stub: true, wouldCall: `${method} https://${api.domain}${routed.uri}${url.search}` }), method);
    }
    log('proxy', ` [-> https://${api.domain}]`);
    const { host, cookie, ...forwarded } = request.headers;
    const upstream = https.request({ host: api.domain, path: routed.uri + url.search, method, headers: forwarded }, (answer) => {
      response.writeHead(answer.statusCode, { ...answer.headers, ...policyHeaders });
      answer.pipe(response);
    });
    upstream.on('error', (error) => send(response, 502, { 'content-type': 'text/plain' }, `emulator: origin unreachable (${error.message})`, method));
    return request.pipe(upstream);
  }

  if (method !== 'GET' && method !== 'HEAD') {
    log(403);
    return send(response, 403, { 'content-type': 'text/plain' }, 'method not allowed for the site bucket', method);
  }
  let relative;
  try { relative = decodeURIComponent(routed.uri).replace(/^\/+/, ''); } catch { relative = '../'; }
  const file = path.resolve(siteDir, relative);
  if (!file.startsWith(siteDir + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    log(404);
    return send(response, 404, { 'content-type': 'application/xml' }, '<Error><Code>NoSuchKey</Code></Error>', method);
  }
  const type = TYPES[path.extname(file).slice(1)] || 'application/octet-stream';
  let answer = { statusCode: 200, headers: { 'content-type': { value: type } } };
  answer = headersFunction({ request: viewerRequest(), response: answer }); // CloudFront hands this the viewer's own request
  log(200);
  return send(response, 200, { ...flat(answer.headers), 'cache-control': cacheControl(relative.split(path.sep).join('/')) }, fs.readFileSync(file), method);
}

http.createServer(serve).listen(port, '127.0.0.1', () => {
  console.log(`emulating the distribution for ${siteDir} on http://127.0.0.1:${port}/  (API: ${apiMode})`);
});
