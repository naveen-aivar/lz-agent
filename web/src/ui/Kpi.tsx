export const Kpi = ({ label, value, hint, tone = "" }: { label: string; value: string; hint?: string; tone?: string }) => (
  <div className={`kpi ${tone ? "kpi-" + tone : ""}`}>
    <div className="kpi-label">{label}</div><div className="kpi-value">{value}</div>{hint && <div className="kpi-hint">{hint}</div>}
  </div>
);
