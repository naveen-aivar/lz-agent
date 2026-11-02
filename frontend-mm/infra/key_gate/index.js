'use strict';

// Sits between the dashboard and an agent's API (one deployment per agent; the environment says which). A signed-in person's Cognito ID token is checked here, then the
// access key is read from Secrets Manager and added for the upstream call. The browser never receives the key.
const crypto = require('crypto');
const https = require('https');

const REGION = 'us-east-1';
const POOL_ID = 'us-east-1_0cYHkw99D';
const CLIENT_ID = 'al2kujlhvm530k6rud25c26mj';
const ISSUER = `https://cognito-idp.us-east-1.amazonaws.com/${POOL_ID}`;

// What differs per agent comes from the environment. The defaults are the TCO agent's, so a gate deployed before this
// existed behaves as it did.
function settings(env) {
  return {
    secretId: env.SECRET_ID || 'ingram-mm-dashboard/tco-access-key',
    upstream: env.UPSTREAM || 'sdcr1ipp07.execute-api.us-east-1.amazonaws.com',
    prefix: env.PREFIX || '/agents/tco/api',
    stage: env.STAGE || 'dev',
    label: env.LABEL || 'tco',
  };
}

// The path the upstream API expects: the dashboard's /agents/<id>/api/x becomes /<stage>/x. Any other path goes through as it came.
function upstreamPath(config, path) {
  if (!path.startsWith(config.prefix)) return path;
  return `/${config.stage}${path.slice(config.prefix.length)}` || `/${config.stage}/`;
}

const SETTINGS = settings(process.env);
const SECRET_ID = SETTINGS.secretId;
const UPSTREAM = SETTINGS.upstream;

let jwks = { at: 0, keys: [] };
let cachedKey = { at: 0, value: '' };

function httpRequest(options, body) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        resolve({ status: res.statusCode || 0, headers: res.headers, body: Buffer.concat(chunks) });
      });
    });
    req.setTimeout(20000, () => req.destroy(new Error('upstream timeout')));
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

function b64url(input) {
  const pad = input.length % 4 === 0 ? '' : '='.repeat(4 - (input.length % 4));
  return Buffer.from(input.replace(/-/g, '+').replace(/_/g, '/') + pad, 'base64');
}

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function hmac(key, value) {
  return crypto.createHmac('sha256', key).update(value).digest();
}

async function signingKeys() {
  if (jwks.keys.length && Date.now() - jwks.at < 60 * 60 * 1000) return jwks.keys;
  const response = await httpRequest({
    hostname: 'cognito-idp.us-east-1.amazonaws.com',
    path: `/${POOL_ID}/.well-known/jwks.json`,
    method: 'GET',
  });
  if (response.status !== 200) throw new Error('jwks');
  jwks = { at: Date.now(), keys: JSON.parse(response.body.toString('utf8')).keys || [] };
  return jwks.keys;
}

async function signedIn(token) {
  const parts = String(token || '').split('.');
  if (parts.length !== 3) return false;
  let header;
  let payload;
  try {
    header = JSON.parse(b64url(parts[0]).toString('utf8'));
    payload = JSON.parse(b64url(parts[1]).toString('utf8'));
  } catch {
    return false;
  }
  if (header.alg !== 'RS256' || !header.kid) return false;
  if (payload.iss !== ISSUER || payload.token_use !== 'id' || payload.aud !== CLIENT_ID) return false;
  if (typeof payload.exp !== 'number' || payload.exp * 1000 < Date.now() - 30000) return false;
  const jwk = (await signingKeys()).find((key) => key.kid === header.kid);
  if (!jwk) return false;
  const verify = crypto.createVerify('RSA-SHA256');
  verify.update(`${parts[0]}.${parts[1]}`);
  verify.end();
  return verify.verify(crypto.createPublicKey({ key: jwk, format: 'jwk' }), b64url(parts[2]));
}

async function accessKey() {
  if (cachedKey.value && Date.now() - cachedKey.at < 5 * 60 * 1000) return cachedKey.value;
  const body = JSON.stringify({ SecretId: SECRET_ID });
  const amzDate = new Date().toISOString().replace(/[:-]|\.\d{3}/g, '');
  const date = amzDate.slice(0, 8);
  const host = `secretsmanager.${REGION}.amazonaws.com`;
  const target = 'secretsmanager.GetSecretValue';
  const token = process.env.AWS_SESSION_TOKEN || '';
  const canonicalHeaders = `content-type:application/x-amz-json-1.1\nhost:${host}\nx-amz-date:${amzDate}\nx-amz-security-token:${token}\nx-amz-target:${target}\n`;
  const signedHeaders = 'content-type;host;x-amz-date;x-amz-security-token;x-amz-target';
  const canonical = ['POST', '/', '', canonicalHeaders, signedHeaders, sha256(body)].join('\n');
  const scope = `${date}/${REGION}/secretsmanager/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, scope, sha256(canonical)].join('\n');
  const signing = hmac(hmac(hmac(hmac(`AWS4${process.env.AWS_SECRET_ACCESS_KEY}`, date), REGION), 'secretsmanager'), 'aws4_request');
  const signature = crypto.createHmac('sha256', signing).update(stringToSign).digest('hex');
  const response = await httpRequest(
    {
      hostname: host,
      path: '/',
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Date': amzDate,
        'X-Amz-Security-Token': token,
        'X-Amz-Target': target,
        Authorization: `AWS4-HMAC-SHA256 Credential=${process.env.AWS_ACCESS_KEY_ID}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`,
        'Content-Length': Buffer.byteLength(body),
      },
    },
    body,
  );
  if (response.status !== 200) throw new Error('secret');
  const value = cleanKey(JSON.parse(response.body.toString('utf8')).SecretString);
  if (!value) throw new Error('secret');
  cachedKey = { at: Date.now(), value };
  return value;
}

// A key with a line break or a space around it is not a valid header value (Node refuses to send it), so whatever the
// secret holds is trimmed. The key itself never contains whitespace.
function cleanKey(value) {
  return String(value || '').trim();
}

function jsonResponse(status, code, message) {
  return {
    statusCode: status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
    body: JSON.stringify({ error: { code, message } }),
  };
}

exports.settings = settings;
exports.cleanKey = cleanKey;
exports.upstreamPath = upstreamPath;
exports.handler = async (event) => {
  const method = String(event.requestContext?.http?.method || event.httpMethod || 'GET').toUpperCase();
  let path = event.rawPath || event.path || '/';
  path = upstreamPath(SETTINGS, path);
  const query = event.rawQueryString ? `?${event.rawQueryString}` : '';
  const headerMap = event.headers || {};
  const authorization = headerMap.authorization || headerMap.Authorization || '';
  const token = authorization.slice(0, 7).toLowerCase() === 'bearer ' ? authorization.slice(7).trim() : '';
  if (method !== 'OPTIONS') {
    try {
      if (!token || !(await signedIn(token))) return jsonResponse(401, 'UNAUTHORIZED', 'Sign in again to use this.');
    } catch (err) {
      console.log(JSON.stringify({ message: `${SETTINGS.label} sign-in check failed`, name: err && err.name }));
      return jsonResponse(401, 'UNAUTHORIZED', 'Sign in again to use this.');
    }
  }
  let key = '';
  if (method !== 'OPTIONS') {
    try {
      key = await accessKey();
    } catch (err) {
      console.log(JSON.stringify({ message: `${SETTINGS.label} key read failed`, name: err && err.name }));
      return jsonResponse(502, 'UPSTREAM', 'The service could not be reached.');
    }
  }
  const body = event.body ? (event.isBase64Encoded ? Buffer.from(event.body, 'base64') : Buffer.from(event.body)) : undefined;
  const headers = { 'x-access-key': key };
  const contentType = headerMap['content-type'] || headerMap['Content-Type'];
  if (contentType) headers['content-type'] = contentType;
  if (!key) delete headers['x-access-key'];
  let upstream;
  try {
    upstream = await httpRequest(
      { hostname: UPSTREAM, path: `${path}${query}`, method, headers },
      body,
    );
  } catch (err) {
    console.log(JSON.stringify({ message: `${SETTINGS.label} upstream failed`, name: err && err.name }));
    return jsonResponse(502, 'UPSTREAM', 'The service could not be reached.');
  }
  const type = upstream.headers['content-type'];
  return {
    statusCode: upstream.status,
    headers: {
      'content-type': Array.isArray(type) ? type[0] : type || 'application/json',
      'cache-control': 'no-store',
    },
    body: upstream.body.toString('utf8'),
  };
};
