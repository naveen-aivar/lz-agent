import { LoaderCircle } from "lucide-react";
import { ACTIVE, STATUS, STATUS_TONE } from "../format.js";
import { Badge } from "./ui/Badge.jsx";
import { Button } from "./ui/Button.jsx";
import { Notice } from "./ui/Notice.jsx";
import { Skeleton } from "./ui/Skeleton.jsx";

// Where a run, landing zone, version or IaC stands: Queued, Working, Ready, Ready with gaps, Failed.
export function StatusBadge({ status }) {
  return (
    <Badge tone={STATUS_TONE[status] || "muted"}>
      {ACTIVE.has(status) ? <LoaderCircle size={12} className="spin" aria-hidden /> : null}
      {STATUS[status] || status}
    </Badge>
  );
}

// A failed load, said plainly, with a way to try again. The technical detail is folded away for whoever helps.
export function ErrorNotice({ what, detail, onRetry }) {
  return (
    <Notice tone="danger" title={`We could not load ${what}.`}
      action={onRetry ? <Button variant="secondary" size="sm" onClick={onRetry}>Try again</Button> : null}>
      Check your connection and try again. If it keeps happening, tell the team that looks after the Architecture Design Agent.
      {detail ? <details className="error-detail"><summary>Details for the team</summary><code>{String(detail)}</code></details> : null}
    </Notice>
  );
}

// Something is still being made: grey bars shaped like the content that will appear. The sentence is for screen readers.
export function Waiting({ children }) {
  return (
    <div className="waiting" role="status" aria-live="polite">
      <span className="sr-only">{children}</span>
      <Skeleton className="waiting-line" />
      <Skeleton className="waiting-line waiting-line-short" />
      <Skeleton className="waiting-block" />
    </div>
  );
}

// The model calls a step made: call n (kind), how many validation errors (the first five listed), tokens.
export function ModelCalls({ attempts, tokens = true }) {
  if (!attempts?.length) return <p className="tone-muted">No model calls were recorded.</p>;
  return (
    <ul className="calls fade-list">
      {attempts.map((a) => (
        <li key={a.n}>
          <b>Call {a.n}</b> <span className="tone-muted">({a.kind})</span>
          {` · ${(a.errors || []).length} validation error${(a.errors || []).length === 1 ? "" : "s"}`}
          {tokens && a.input_tokens ? ` · ${a.input_tokens.toLocaleString()} in / ${(a.output_tokens || 0).toLocaleString()} out tokens` : ""}
          {(a.errors || []).length ? <ul className="calls-errors">{a.errors.slice(0, 5).map((e) => <li key={e} className="tone-muted">{e}</li>)}</ul> : null}
        </li>
      ))}
    </ul>
  );
}
