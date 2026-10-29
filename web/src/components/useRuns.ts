import { useEffect, useState } from "react";
import type { Client, RunSummary } from "../api/client";

/** The caller's runs, loaded once. `error` names why they could not be loaded. */
export function useRuns(api: Client): { runs: RunSummary[] | null; total: number | undefined; error: string } {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [total, setTotal] = useState<number | undefined>(undefined);
  const [error, setError] = useState("");
  useEffect(() => {
    api.listRuns().then((r) => { setRuns(r.runs); setTotal(r.total); }).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [api]);
  return { runs, total, error };
}
