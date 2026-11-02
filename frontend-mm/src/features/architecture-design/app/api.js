// All calls go to the agent's API (deployment/api). In dev, BASE is "/api" and Vite proxies it to VITE_API_BASE. In a
// production build BASE is the absolute VITE_API_BASE, so the browser calls API Gateway directly (its CORS allows it).
// The deployed API needs the shared access key in X-Access-Key: it is asked for once (a dialog, see AccessKeyDialog)
// and kept for this browser tab only. The local API has no key and ignores it. The saved sample run answers its own
// paths (sampleRun.js) without calling the API.
import { sampleRun } from "./sampleRun.js";
import { idToken } from "@/shared/auth/cognito";

const BASE = "/agents/architecture-design/api";

const KEY_STORE = "archAccessKey";
const writeKey = (k) => { try { if (k) sessionStorage.setItem(KEY_STORE, k); else sessionStorage.removeItem(KEY_STORE); } catch { /* private mode */ } };

// One question at a time while several requests fail together. The dialog answers through `answerKey`.
let keyResolve = null;
export function answerKey(key) {
  const k = (key || "").trim();
  writeKey(k);
  const done = keyResolve;
  keyResolve = null;
  if (done) done(k);
}

async function req(method, path, body) {
  const sample = await sampleRun.handle(method, path, body);
  if (sample) return sample;
  const headers = { "Content-Type": "application/json" };
  const token = await idToken().catch(() => null);
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${BASE}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await resp.json().catch(() => ({}));
  if (resp.status === 401) throw new Error("Sign in again to use this.");
  if (!resp.ok) throw new Error(data.error?.message || data.error || data.message || `HTTP ${resp.status}`);
  return data;
}

const enc = encodeURIComponent;
const post = (path, body) => req("POST", path, body);
const query = (q) => Object.entries(q).filter(([, v]) => v !== undefined && v !== null).map(([k, v]) => `${k}=${enc(v)}`).join("&");

// Output files never change once written, so each is fetched once per page load.
const fileCache = new Map();

export const api = {
  session: () => req("GET", "/session"),
  async runs() {
    const { runs } = await req("GET", "/runs");
    const sample = await sampleRun.summary().catch(() => null);
    return sample ? [sample, ...runs.filter((r) => r.run_id !== sample.run_id)] : runs;
  },
  run: (id) => req("GET", `/runs/${enc(id)}`),
  start: (body) => post("/runs", body),
  // query: {lz} (landing-zone files), {version} (design files), {version, iac} (IaC files)
  file(id, q, name) {
    const key = `${id}?${query(q)}/${name}`;
    if (!fileCache.has(key)) {
      fileCache.set(key, req("GET", `/runs/${enc(id)}/files/${enc(name)}?${query(q)}`).catch((err) => { fileCache.delete(key); throw err; }));
    }
    return fileCache.get(key);
  },
  lzRetry: (id) => post(`/runs/${enc(id)}/lz`, {}),
  lzRevise: (id, instruction) => post(`/runs/${enc(id)}/lz/revise`, { instruction }),
  lzApprove: (id, lz) => post(`/runs/${enc(id)}/lz/approve`, { lz }),
  revise: (id, body) => post(`/runs/${enc(id)}/revise`, body),
  approve: (id, version) => post(`/runs/${enc(id)}/approve`, { version }),
  iacStart: (id, version) => post(`/runs/${enc(id)}/iac`, { version }),
  iacRevise: (id, version, instruction) => post(`/runs/${enc(id)}/iac/revise`, { version, instruction }),
  iacApprove: (id, version, iac) => post(`/runs/${enc(id)}/iac/approve`, { version, iac }),
};

// A file as the API returns it ({content_type, encoding, data}) as a Blob, a data: URL, or parsed JSON.
export function toBlob(file) {
  if (file.encoding === "base64") {
    const bin = atob(file.data);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: file.content_type });
  }
  return new Blob([file.data], { type: `${file.content_type};charset=utf-8` });
}
export function imageUrl(file, name) {
  const type = name.endsWith(".svg") ? "image/svg+xml" : "image/png";
  const data = file.encoding === "base64" ? file.data : btoa(unescape(encodeURIComponent(file.data)));
  return `data:${type};base64,${data}`;
}
export function saveFile(file, filename) {
  const url = URL.createObjectURL(toBlob(file));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

export const toBase64 = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
  reader.onerror = () => reject(new Error(`could not read ${file.name}`));
  reader.readAsDataURL(file);
});
