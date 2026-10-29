import { useState } from "react";
import type { Client } from "../api/client";
import { DeployDialog } from "./DeployDialog";
import { RunsTable } from "./RunsTable";
import { useRuns } from "./useRuns";

export function RunsPage({ api, onOpen }: { api: Client; onOpen: (runId: string) => void }) {
  const { runs, error } = useRuns(api);
  const [deployFor, setDeployFor] = useState<string | null>(null);
  if (error) return <p className="errtext" role="alert">{error}</p>;
  if (!runs) return <p className="empty">Loading…</p>;
  return (
    <>
      <h1 className="page-title">Run history</h1>
      <p className="page-sub">
        Design runs generate IaC from a SOW; deploy runs apply AWS Transform in your organization and produce a foundation
        attestation. Open any run for progress, questions and activity. A deploy run that stopped can be resumed from where it stopped.
      </p>
      <div className="panel panel-pad"><RunsTable runs={runs} onDeploy={setDeployFor} /></div>
      {deployFor && (
        <DeployDialog designRunId={deployFor} api={api} onCancel={() => setDeployFor(null)}
          onStarted={(id) => { setDeployFor(null); onOpen(id); }} />
      )}
    </>
  );
}
