import { useState } from "react";
import { PAGE_SIZE } from "../logic/stats";
import type { Client } from "../api/client";
import { DeployDialog } from "./DeployDialog";
import { RunsTable } from "./RunsTable";
import { useRuns } from "./useRuns";

export function RunsPage({ api, onOpen }: { api: Client; onOpen: (runId: string) => void }) {
  const { runs, total, error } = useRuns(api);
  const [deployFor, setDeployFor] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE_SIZE);
  if (error) return <p className="errtext" role="alert">{error}</p>;
  if (!runs) return <p className="empty">Loading…</p>;
  return (
    <>
      <h1 className="page-title">Run history</h1>
      <p className="page-sub">
        Design runs generate IaC from a SOW; deploy runs apply AWS Transform in your organization and produce a foundation
        attestation. Open any run for progress, questions and activity. A deploy run that stopped can be resumed from where it stopped.
      </p>
      <div className="panel panel-pad">
        <RunsTable runs={runs.slice(0, shown)} onDeploy={setDeployFor} />
        <div className="card-head" style={{ marginTop: 12 }}>
          <span className="hint" data-testid="run-count">
            Showing {Math.min(shown, runs.length)} of {total ?? runs.length} runs
            {total !== undefined && total > runs.length ? ` (the newest ${runs.length} can be listed)` : ""}
          </span>
          {shown < runs.length && (
            <button type="button" className="btn btn-sm" onClick={() => setShown(shown + PAGE_SIZE)}>
              Show {Math.min(PAGE_SIZE, runs.length - shown)} more
            </button>
          )}
        </div>
      </div>
      {deployFor && (
        <DeployDialog designRunId={deployFor} api={api} onCancel={() => setDeployFor(null)}
          onStarted={(id) => { setDeployFor(null); onOpen(id); }} />
      )}
    </>
  );
}
