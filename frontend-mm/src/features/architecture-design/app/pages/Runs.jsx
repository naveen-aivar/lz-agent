import { FilePlus2 } from "lucide-react";
import { ButtonLink } from "../components/ui/Button.jsx";
import { Card } from "../components/ui/Card.jsx";
import { DataTable } from "../components/ui/DataTable.jsx";
import { EmptyState } from "../components/ui/EmptyState.jsx";
import { PageHeader } from "../components/ui/PageHeader.jsx";
import { SkeletonText } from "../components/ui/Skeleton.jsx";
import { ErrorNotice, StatusBadge } from "../components/bits.jsx";
import { ago, when } from "../format.js";
import { href, navigate } from "../useRoute.js";
import RunDetail from "./RunDetail.jsx";

// How many placeholder rows the list shows while the runs load: enough to fill a screen.
const SKELETON_ROWS = 15;

export default function Runs({ id, runs }) {
  return id ? <RunDetail key={id} id={id} listRun={runs.data?.find((r) => r.run_id === id)} /> : <RunList runs={runs} />;
}

// Where a run has got to, in words: the landing zone, or the design version (and the landing zone when revised).
const stepOf = (r) => (r.version > 0 ? `Version ${r.version}` : "Landing zone");

function RunList({ runs }) {
  const loading = !runs.data && !runs.error;
  const newButton = loading
    ? <button type="button" className="btn btn-primary btn-md" disabled><FilePlus2 size={16} aria-hidden /> New architecture</button>
    : <ButtonLink href={href("new")}><FilePlus2 size={16} aria-hidden /> New architecture</ButtonLink>;
  return (
    <>
      <PageHeader title="Runs" description="Every architecture, newest first. Open one to follow its steps and outputs." actions={newButton} />
      {runs.error && !runs.data ? <ErrorNotice what="the runs" detail={runs.error} onRetry={runs.refresh} /> : (
        <Card flush>
          <DataTable label="Runs" loading={loading} loadingRows={SKELETON_ROWS} rows={runs.data} rowKey={(r) => r.run_id}
            onRowClick={(r) => navigate("runs", r.run_id)}
            empty={<EmptyState title="No runs yet" description="Start a new architecture to see it here."
              action={<ButtonLink variant="secondary" size="sm" href={href("new")}>New architecture</ButtonLink>} />}
            columns={[
              { key: "title", label: "Architecture", skeleton: <><SkeletonText>Billing dispute assistant</SkeletonText><span className="cell-sub"><SkeletonText>srs.md</SkeletonText></span></>,
                render: (r) => <><a href={href("runs", r.run_id)} className="cell-main">{r.title || r.srs_filename || "Untitled"}</a><span className="cell-sub">{r.srs_filename && r.title ? r.srs_filename : r.run_id === "sample-run" ? "Saved sample run" : "Pasted text"}</span></> },
              { key: "started", label: "Started", skeleton: <><SkeletonText>28 Oct 2026, 15:27</SkeletonText><span className="cell-sub"><SkeletonText>2h ago</SkeletonText></span></>,
                render: (r) => <><span>{when(r.created_at)}</span><span className="cell-sub">{ago(r.created_at)}</span></> },
              { key: "status", label: "Status", skeleton: <SkeletonText>Ready with gaps</SkeletonText>, render: (r) => <StatusBadge status={r.status} /> },
              { key: "step", label: "Step", skeleton: <><SkeletonText>Version 2</SkeletonText><span className="cell-sub"><SkeletonText>Landing zone 2</SkeletonText></span></>,
                render: (r) => <><span>{stepOf(r)}</span>{r.lz > 1 ? <span className="cell-sub">Landing zone {r.lz}</span> : null}</> },
            ]}
          />
        </Card>
      )}
    </>
  );
}
