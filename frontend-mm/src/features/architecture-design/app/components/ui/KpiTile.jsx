import InfoHint from "./InfoHint.jsx";
import { Skeleton, SkeletonText } from "./Skeleton.jsx";

// A number with its name, as on the portal's dashboard: the title (and its "i") on top, then the tinted icon and the figure on one line,
// then a short hint. Every tile has the same three rows at the same height, so a row of tiles lines up. tone tints the icon
// (default | success | warning | danger | violet | teal); valueTone colours the figure. With onClick the whole tile opens something: a
// transparent button sits over it, so the "i" stays its own control.
export function KpiTile({ icon: Icon, tone = "default", label, value, hint, hintTone, info, valueTone, onClick, loading = false, index = 0 }) {
  return (
    <div className={`kpi${onClick && !loading ? " kpi-clickable" : ""}${loading ? "" : " animate-fade-up"}`} style={{ "--stagger": index }}>
      <p className="kpi-label">
        <span className="kpi-label-text" title={loading ? undefined : label}>{loading ? <SkeletonText>Label of a tile</SkeletonText> : label}</span>
        {info && !loading ? <InfoHint {...info} /> : null}
      </p>
      <div className="kpi-top">
        {Icon ? (loading ? <Skeleton className="kpi-icon" /> : <span className={`kpi-icon kpi-icon-${tone}`}><Icon size={20} aria-hidden /></span>) : null}
        <p className={`kpi-value font-display${valueTone ? ` tone-${valueTone}` : ""}`}>
          {loading ? <SkeletonText>00</SkeletonText> : (value ?? "–")}
        </p>
      </div>
      {hint !== undefined ? (
        <p className={`kpi-hint${hintTone ? ` tone-${hintTone}` : ""}`}>{loading ? <SkeletonText>A short hint</SkeletonText> : hint}</p>
      ) : null}
      {onClick && !loading ? (
        <button type="button" className="kpi-hit" onClick={onClick} aria-label={`${label}: ${value ?? "none"}. Show the details`} />
      ) : null}
    </div>
  );
}
