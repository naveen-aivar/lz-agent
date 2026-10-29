import { useEffect, useMemo, useState } from "react";
import type { Client, RunSummary } from "../api/client";
import { groupProjects } from "../logic/projects";
import type { Project } from "../logic/projects";
/** The caller's runs, loaded once, and the projects they make up. `error` names why they could not be loaded. */
export function useRuns(api: Pick<Client, "listRuns">): { runs: RunSummary[] | null; projects: Project[] | null; total: number | undefined; error: string } {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [total, setTotal] = useState<number | undefined>(undefined);
  const [error, setError] = useState("");
  useEffect(() => {
    api.listRuns().then((r) => { setRuns(r.runs); setTotal(r.total); }).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [api]);
  const projects = useMemo(() => (runs ? groupProjects(runs) : null), [runs]);
  return { runs, projects, total, error };
}
