import type { Schemas } from "../api/client";

type Scope = Schemas["ScopeData"]["scope"];
const names = (v: unknown): string[] =>
  Array.isArray(v) ? v.map((x) => (x && typeof x === "object" ? String((x as { path?: string; name?: string }).path ?? (x as { name?: string }).name ?? "") : String(x))).filter(Boolean) : [];

/** The approved design the deploy run builds: Region, OUs and accounts, and the diagram source. */
export function DesignPanel({ scope, diagram }: { scope: Scope; diagram: string }) {
  const regions = (scope.regions ?? {}) as { home?: string; governed?: string[] };
  return (
    <div className="design">
      <p><strong>Home Region:</strong> {regions.home ?? "not set"}</p>
      <h3>Organizational units</h3>
      <ul>{names(scope.ous).map((n) => <li key={n}>{n}</li>)}</ul>
      <h3>Accounts</h3>
      <ul>{names(scope.accounts).map((n) => <li key={n}>{n}</li>)}</ul>
      {diagram && (
        <details>
          <summary>Organization diagram (Mermaid source)</summary>
          <pre>{diagram}</pre>
        </details>
      )}
    </div>
  );
}
