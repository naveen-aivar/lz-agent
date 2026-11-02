import { EmptyState } from "./EmptyState.jsx";
import { SkeletonText } from "./Skeleton.jsx";

// A table that becomes a list of cards on a phone. Each column is
//   { key, label, render?(row), align?: "end", skeleton?: node, info?: node, className? }
// While `loading`, the real header is shown with placeholder rows of the same shape.
export function DataTable({ columns, rows, rowKey, onRowClick, empty, loading = false, loadingRows = 4, label }) {
  if (!loading && !rows?.length) return empty || <EmptyState title="Nothing here" />;
  const body = loading ? Array.from({ length: loadingRows }, (_, i) => ({ __skeleton: i })) : rows;
  return (
    <div className="tbl-wrap">
      <table className="tbl" aria-label={label} aria-busy={loading || undefined}>
        <thead>
          <tr>{columns.map((c) => <th key={c.key ?? c.label} scope="col" className={c.align === "end" ? "num" : ""}><span className="th-inner">{c.label || <span className="sr-only">{c.srLabel}</span>}{c.info}</span></th>)}</tr>
        </thead>
        <tbody className="fade-list">
          {body.map((r, i) => (
            <tr key={loading ? r.__skeleton : rowKey(r, i)} className={onRowClick && !loading ? "tbl-click" : ""}
              onClick={onRowClick && !loading ? (e) => { if (!e.target.closest("a,button,input,select,textarea")) onRowClick(r); } : undefined}>
              {columns.map((c) => (
                <td key={c.key ?? c.label} data-label={c.label || undefined} className={`${c.align === "end" ? "num" : ""} ${c.className || ""}`.trim()}>
                  <div className="td-content">{loading ? (c.skeleton ?? <SkeletonText>Placeholder</SkeletonText>) : c.render ? c.render(r, i) : r[c.key]}</div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
