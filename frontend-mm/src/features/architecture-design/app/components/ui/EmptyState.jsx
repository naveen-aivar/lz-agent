import { Inbox } from "lucide-react";

export function EmptyState({ title, description, action, icon: Icon = Inbox }) {
  return (
    <div className="empty-state">
      <span className="empty-icon"><Icon size={20} aria-hidden /></span>
      <p className="empty-title">{title}</p>
      {description ? <p className="empty-text">{description}</p> : null}
      {action ? <div className="empty-action">{action}</div> : null}
    </div>
  );
}
