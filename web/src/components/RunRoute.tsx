import { useEffect, useState } from "react";
import type { Client, Run } from "../api/client";
import type { StepId } from "../logic/journey";
import type { Theme } from "../theme";
import { ProjectPage } from "./ProjectPage";
import { RunPage } from "./RunPage";
/** Opens a run: a design run, or a deploy run built from one, opens its project; a deploy run with no design run opens alone. */
export function RunRoute({ runId, step, api, canAnswer, userSub, theme, onStep, onCrumb }: {
  runId: string; step: string | null; api: Client; canAnswer: boolean; userSub: string; theme: Theme;
  onStep: (designId: string, step: StepId) => void; onCrumb: (name: string) => void;
}) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setRun(null); setError("");
    api.getRun(runId).then((r) => setRun(r.run)).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [api, runId]);
  if (error) return <p className="errtext" role="alert">{error}</p>;
  if (!run) return <p className="empty">Loading…</p>;
  if (run.runKind === "deploy" && !run.designRunId) {
    return <RunPage runId={runId} api={api} canAnswer={canAnswer} userSub={userSub} theme={theme} onCrumb={onCrumb} />;
  }
  const designId = run.runKind === "deploy" ? run.designRunId! : runId;
  return (
    <ProjectPage key={designId} designId={designId} api={api} canAnswer={canAnswer} userSub={userSub} theme={theme}
      step={step ?? (run.runKind === "deploy" ? "deploy" : null)} onStep={(s) => onStep(designId, s)} onCrumb={onCrumb} />
  );
}
