// Words and numbers as the console shows them. Status names are the ones the old console used.

export const ACTIVE = new Set(["queued", "running"]);
export const STATUS = { queued: "Queued", running: "Working", completed: "Ready", partial: "Ready with gaps", failed: "Failed" };
export const STATUS_TONE = { queued: "info", running: "info", completed: "success", partial: "warning", failed: "danger" };
export const CHECK = { pass: "Passed", pass_with_warnings: "Passed", fail: "Failed" };

export const MAX_TEXT = 200000;
export const MIN_TEXT = 200;
export const MAX_FILE_BYTES = 4 * 1024 * 1024;
export const FILE_EXT = ["md", "markdown", "txt", "docx", "pdf"];
export const IAC_NAME = "Landing Zone - IaC";

export const when = (iso) => (iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "");
export const timeOf = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "");
export const size = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
export const num = (n) => (typeof n === "number" ? n.toLocaleString() : String(n ?? "–"));
export const plural = (n, word, many = `${word}s`) => `${num(n)} ${n === 1 ? word : many}`;
// 42 -> "42 s", 312 -> "5.2 min": how long the agent took.
export const dur = (s) => (typeof s !== "number" ? "–" : s < 60 ? `${Math.max(1, Math.round(s))} s` : `${Math.round(s / 6) / 10} min`);
// "needs-input" -> "needs input": a status word from the API, said in words.
// A reason from the API as a sentence: capital first, full stop last.
export const sentence = (s) => { const t = String(s || "Unknown error").trim(); return `${t.charAt(0).toUpperCase()}${t.slice(1)}${/[.!?]$/.test(t) ? "" : "."}`; };
export const words = (s) => String(s ?? "–").replace(/[-_]+/g, " ");

export function ago(iso) {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// "Version 2 (revised) · older landing zone · Ready" and the like, for the version pickers.
export const versionLabel = (x) => `Version ${x.version}${x.kind === "revise" ? " (revised)" : ""}`;
export const lzLabel = (x) => `Landing zone ${x.lz}${x.kind === "revise" ? " (revised)" : ""}`;
export const iacLabel = (x) => `${IAC_NAME} ${x.iac}${x.kind === "revise" ? " (revised)" : ""}`;

// A file name made from the run's title: what a downloaded file is saved as.
export const runName = (title) => (title || "architecture").replace(/[^\w-]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "architecture";

// The landing-zone versions in order, and the newest one that finished.
export const lzVersions = (cur) => (cur?.lz_versions || []).slice().sort((a, b) => a.lz - b.lz);
export const newestLz = (cur) => lzVersions(cur).filter((x) => x.status === "completed").pop();

// The design version on screen: the one picked, else the latest (or the latest complete one when the latest failed).
export function selectedVersion(cur, picked) {
  const versions = cur?.versions || [];
  if (picked) return versions.find((v) => v.version === picked) || versions[versions.length - 1];
  const latest = versions[versions.length - 1];
  if (latest && latest.status === "failed" && cur.run.latest_complete_version) {
    return versions.find((v) => v.version === cur.run.latest_complete_version) || latest;
  }
  return latest;
}
export const isDone = (v) => !!v && (v.status === "completed" || v.status === "partial");
export const hasOutputs = (v) => !!(v && v.files && v.files["adr.md"]);

// The IaC versions of one design version, oldest first ("lz" was the IaC number in an older release).
export const iacItems = (cur, v) => (v ? (cur?.iac || cur?.landing_zones || [])
  .filter((x) => x.version === v.version).map((x) => ({ ...x, iac: x.iac ?? x.lz })).sort((a, b) => a.iac - b.iac) : []);

// "usage_gb_month" -> "usage GB month"
export const humanKey = (k) => k.replace(/_/g, " ").replace(/\b(gb|tb|mb|vcpu|iops|az|lcu|api|rps)\b/gi, (m) => m.toUpperCase());
