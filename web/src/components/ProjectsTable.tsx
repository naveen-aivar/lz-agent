import type { Project } from "../logic/projects";
import { ago } from "../logic/format";
import { Badge } from "../ui/Badge";
/** One row per customer: where the project is and the one thing to do next. */
export function ProjectsTable({ projects, empty }: { projects: Project[]; empty?: string }) {
  if (!projects.length) return <p className="empty">{empty ?? <>Nothing here yet. <a href="#/new">Start with a SOW</a>.</>}</p>;
  return (
    <div className="tbl-wrap">
      <table>
        <thead><tr><th>Customer</th><th>Where it is</th><th>Started</th><th /></tr></thead>
        <tbody>
          {projects.map((p) => {
            const error = p.deploy?.status === "FAILED" ? p.deploy.error : p.design?.status === "FAILED" ? p.design.error : "";
            return (
              <tr key={p.id} className="click">
                <td className="name"><a href={`#/run/${p.id}`}>{p.name}</a></td>
                <td><Badge tone={p.stage.tone}>{p.stage.label}</Badge>{error && <div className="errtext small">{error.slice(0, 80)}</div>}</td>
                <td>{ago(p.createdAt)}</td>
                <td><a className={p.stage.id === "needs_you" ? "btn btn-sm btn-primary" : ""} href={`#/run/${p.id}`}>{p.stage.next} →</a></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
