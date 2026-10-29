import { useState } from "react";
import type { Client, DeployRequest } from "../api/client";

type Method = "role" | "keys" | "platform";
const MAP = /^(none|(mig_ec2_|comm_ec2_|mig|sap|oracle|comm)[A-Za-z0-9]{1,40})$/;
const EMAIL = /^[A-Za-z0-9._-]{1,64}@([A-Za-z0-9-]+\.)+[A-Za-z]{2,63}$/;

/** Builds the POST /runs/{id}/deploy body from the form, or throws a message naming what is wrong. */
export function buildDeployRequest(f: {
  method: Method; accountId: string; roleArn: string; externalId: string; accessKeyId: string;
  secretAccessKey: string; sessionToken: string; accountEmail: string; mapAgreement: string; targetRegion: string;
  applyScps: boolean;
}): DeployRequest {
  const body: DeployRequest = { applyScps: f.applyScps };
  if (f.method !== "platform") {
    if (!/^\d{12}$/.test(f.accountId.trim())) throw new Error("Target account ID must be 12 digits");
    if (f.method === "role") {
      if (!f.roleArn.trim()) throw new Error("Role ARN is required");
      if (!f.externalId.trim()) throw new Error("External ID is required for the IAM role method");
      body.deployTarget = { accountId: f.accountId.trim(), roleArn: f.roleArn.trim(), externalId: f.externalId.trim() };
    } else {
      if (!f.accessKeyId.trim() || !f.secretAccessKey.trim()) throw new Error("Access key ID and secret are required");
      body.deployTarget = { accountId: f.accountId.trim(), accessKeyId: f.accessKeyId.trim(), secretAccessKey: f.secretAccessKey.trim() };
      if (f.sessionToken.trim()) body.deployTarget.sessionToken = f.sessionToken.trim();
    }
  }
  const email = f.accountEmail.trim();
  if (email) {
    if (email.includes("+") || !EMAIL.test(email)) throw new Error("Account email must look like prefix@domain, without a +");
    body.accountEmail = email;
  }
  const map = f.mapAgreement.trim();
  if (map) {
    if (!MAP.test(map)) throw new Error("MAP agreement must be none or the full MAP tag, such as mig12345");
    body.mapAgreement = map;
  }
  if (f.targetRegion.trim()) body.targetRegion = f.targetRegion.trim();
  return body;
}

export function DeployDialog({ designRunId, api, onStarted, onCancel }: {
  designRunId: string;
  api: Pick<Client, "startDeploy" | "verifyDeployTarget">;
  onStarted: (runId: string) => void;
  onCancel: () => void;
}) {
  const [f, setF] = useState({ method: "role" as Method, accountId: "", roleArn: "", externalId: "", accessKeyId: "",
    secretAccessKey: "", sessionToken: "", accountEmail: "", mapAgreement: "", targetRegion: "", applyScps: true });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function run(kind: "verify" | "start") {
    setBusy(true);
    setMessage("");
    try {
      const body = buildDeployRequest(f);
      if (kind === "verify") {
        if (!body.deployTarget) throw new Error("Choose the role or keys method to test a connection");
        const r = await api.verifyDeployTarget({ designRunId, deployTarget: body.deployTarget });
        setMessage(r.ok ? String(r.message ?? "Connection OK") : `Failed: ${String(r.error ?? "unknown error")}`);
      } else {
        const r = await api.startDeploy(designRunId, body);
        onStarted(r.runId);
      }
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal"><div className="dialog" role="dialog" aria-modal="true" aria-label="Deploy target account">
      <h2>Deploy target</h2>
      <label>Auth method
        <select value={f.method} onChange={set("method")}>
          <option value="role">IAM role (AssumeRole)</option>
          <option value="keys">Access keys (session)</option>
          <option value="platform">Platform account only</option>
        </select>
      </label>
      {f.method !== "platform" && <label>Target account ID<input value={f.accountId} onChange={set("accountId")} inputMode="numeric" /></label>}
      {f.method === "role" && (<>
        <label>Role ARN<input value={f.roleArn} onChange={set("roleArn")} /></label>
        <label>External ID<input value={f.externalId} onChange={set("externalId")} autoComplete="off" /></label>
      </>)}
      {f.method === "keys" && (<>
        <label>Access key ID<input value={f.accessKeyId} onChange={set("accessKeyId")} autoComplete="off" /></label>
        <label>Secret access key<input type="password" value={f.secretAccessKey} onChange={set("secretAccessKey")} autoComplete="off" /></label>
        <label>Session token (optional)<input value={f.sessionToken} onChange={set("sessionToken")} autoComplete="off" /></label>
      </>)}
      <label>Account email (optional)
        <span className="hint">prefix@domain for the new accounts, without a +. Transform adds +account-name.</span>
        <input type="email" value={f.accountEmail} onChange={set("accountEmail")} />
      </label>
      <label className="check">
        <input type="checkbox" checked={f.applyScps} onChange={(e) => setF({ ...f, applyScps: e.target.checked })} />
        Apply SCPs
      </label>
      <span className="hint">Ticked: the agent stages the Service Control Policies and controls AWS Transform recommends for the Workloads OUs. Unticked: it skips them.</span>
      <label>MAP agreement (optional)
        <span className="hint">none, or the full MAP tag such as mig12345. The agent answers Transform's MAP question from it.</span>
        <input value={f.mapAgreement} onChange={set("mapAgreement")} placeholder="none" />
      </label>
      <label>Control Tower Region override (optional)<input value={f.targetRegion} onChange={set("targetRegion")} placeholder="us-east-1" /></label>
      {message && <p role="status" className="hint">{message}</p>}
      <div className="row">
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
        {f.method !== "platform" && <button type="button" className="btn" onClick={() => run("verify")} disabled={busy}>Test connection</button>}
        <button type="button" className="btn btn-primary" onClick={() => run("start")} disabled={busy}>Start deploy run</button>
      </div>
    </div></div>
  );
}
