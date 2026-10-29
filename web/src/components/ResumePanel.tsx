import { useState } from "react";
import type { Client, ResumeRequest, Run } from "../api/client";

/** The deploy target a run recorded (no secrets are ever returned to the browser). */
const targetOf = (run: Run): { mode?: string; accountId?: string } | null =>
  run.deployTarget && typeof run.deployTarget === "object" ? (run.deployTarget as { mode?: string; accountId?: string }) : null;

/** Builds the resume body: new keys when the run used keys (they were deleted when it stopped), else nothing. */
export function buildResumeRequest(
  target: { mode?: string; accountId?: string } | null,
  f: { accessKeyId: string; secretAccessKey: string; sessionToken: string },
): ResumeRequest {
  if (target?.mode !== "keys") return {};
  if (!target.accountId) throw new Error("The run did not record its target account");
  if (!f.accessKeyId.trim() || !f.secretAccessKey.trim()) throw new Error("Access key ID and secret are required: the stored keys were deleted when the run stopped");
  const deployTarget: NonNullable<ResumeRequest["deployTarget"]> = {
    accountId: target.accountId, accessKeyId: f.accessKeyId.trim(), secretAccessKey: f.secretAccessKey.trim(),
  };
  if (f.sessionToken.trim()) deployTarget.sessionToken = f.sessionToken.trim();
  return { deployTarget };
}

/** A failed deploy run continues from its checkpoint (same run, same Transform job) instead of starting over. */
export function ResumePanel({ run, api, onResumed }: { run: Run; api: Pick<Client, "resumeRun">; onResumed: () => void }) {
  const target = targetOf(run);
  const [f, setF] = useState({ accessKeyId: "", secretAccessKey: "", sessionToken: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!run.resumable) {
    return <p className="hint" data-testid="not-resumable">This run recorded no progress, so there is nothing to continue. Start a new deploy run.</p>;
  }

  async function resume() {
    setBusy(true);
    setError("");
    try {
      await api.resumeRun(run.runId, buildResumeRequest(target, f));
      onResumed();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="hitl" aria-labelledby="resume-heading">
      <h2 id="resume-heading">Continue this run</h2>
      <p>
        Resuming keeps this run, its progress and its AWS Transform job, and carries on from where it stopped. Nothing
        starts over. If the Transform job itself was stopped in the Transform console, the resumed run will say so.
      </p>
      {target?.mode === "keys" && (
        <div className="dialog">
          <p className="hint">This run used access keys, and they were deleted when it stopped. Send keys for account <code>{target.accountId}</code>.</p>
          <label>Access key ID<input value={f.accessKeyId} autoComplete="off" onChange={(e) => setF({ ...f, accessKeyId: e.target.value })} /></label>
          <label>Secret access key<input type="password" value={f.secretAccessKey} autoComplete="off" onChange={(e) => setF({ ...f, secretAccessKey: e.target.value })} /></label>
          <label>Session token (optional)<input value={f.sessionToken} autoComplete="off" onChange={(e) => setF({ ...f, sessionToken: e.target.value })} /></label>
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <button type="button" className="btn btn-primary" disabled={busy} onClick={resume}>{busy ? "Resuming…" : "Resume run"}</button>
    </section>
  );
}
