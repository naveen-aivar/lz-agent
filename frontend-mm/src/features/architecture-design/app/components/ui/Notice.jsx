import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";

const ICON = { info: Info, success: CircleCheck, warning: TriangleAlert, danger: CircleAlert };

// A message in the page: tone is info | success | warning | danger. Errors are announced to screen readers.
export function Notice({ tone = "info", title, children, action, className = "" }) {
  const Icon = ICON[tone] || Info;
  return (
    <div className={`notice notice-${tone} ${className}`.trim()} role={tone === "danger" ? "alert" : "status"}>
      <Icon size={18} aria-hidden className="notice-icon" />
      <div className="notice-body">
        {title ? <p className="notice-title">{title}</p> : null}
        {children ? <div className="notice-text">{children}</div> : null}
        {action ? <div className="notice-action">{action}</div> : null}
      </div>
    </div>
  );
}
