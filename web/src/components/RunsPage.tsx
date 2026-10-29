import { useMemo, useState } from "react";
import type { Client } from "../api/client";
import { countProjects, filterProjects } from "../logic/projects";
import type { ProjectFilter } from "../logic/projects";
import { PAGE_SIZE } from "../logic/stats";
import { ProjectsTable } from "./ProjectsTable";
import { useRuns } from "./useRuns";
const STATUS: [ProjectFilter, string][] = [["all", "All"], ["attention", "Needs you"], ["active", "In progress"], ["complete", "Complete"], ["failed", "Stopped"]];
export function RunsPage({ api }: { api: Client }) {
  const { projects, runs, total, error } = useRuns(api);
  const [shown, setShown] = useState(PAGE_SIZE);
  const [status, setStatus] = useState<ProjectFilter>("all");
  const [query, setQuery] = useState("");
  const counts = useMemo(() => (projects ? countProjects(projects) : null), [projects]);
  const rows = useMemo(() => (projects ? filterProjects(projects, { status, query }) : []), [projects, status, query]);
  if (error) return <p className="errtext" role="alert">{error}</p>;
  if (!projects || !counts || !runs) return <p className="empty">Loading…</p>;
  return (
    <>
      <div className="page-head">
        <div><h1 className="page-title">Projects</h1><p className="page-sub">One row per customer, from SOW to landing zone. Open a project to continue where you left off.</p></div>
        <a className="btn btn-primary" href="#/new">New project</a>
      </div>
      <div className="panel panel-pad">
        <div className="filters">
          <div className="chips" role="group" aria-label="Filter by state">
            {STATUS.map(([id, label]) => (
              <button key={id} type="button" className="chip" aria-pressed={status === id} onClick={() => { setStatus(id); setShown(PAGE_SIZE); }}>
                {label} <span className="count">{counts[id]}</span>
              </button>
            ))}
          </div>
          <input type="search" aria-label="Search projects" placeholder="Search customer or run id" value={query} onChange={(e) => { setQuery(e.target.value); setShown(PAGE_SIZE); }} className="search" />
        </div>
        <ProjectsTable projects={rows.slice(0, shown)} empty={projects.length ? "No projects match these filters." : undefined} />
        <div className="card-head" style={{ marginTop: 12 }}>
          <span className="hint" data-testid="run-count">
            Showing {Math.min(shown, rows.length)} of {rows.length} matching projects
            {total !== undefined && total > runs.length ? `; only the newest ${runs.length} runs can be listed (${total} in total)` : ""}
          </span>
          {shown < rows.length && (
            <button type="button" className="btn btn-sm" onClick={() => setShown(shown + PAGE_SIZE)}>Show {Math.min(PAGE_SIZE, rows.length - shown)} more</button>
          )}
        </div>
      </div>
    </>
  );
}
