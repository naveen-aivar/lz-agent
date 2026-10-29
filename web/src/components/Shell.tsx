import type { ReactNode } from "react";

export type Nav = "dashboard" | "runs";

/** The classic UI's frame: INGRAM sidebar, breadcrumb topbar, content. */
export function Shell({ nav, crumb, email, onSignOut, children }: {
  nav: Nav; crumb: string; email?: string; onSignOut: () => void; children: ReactNode;
}) {
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand"><span className="brand-logo"><span className="in">IN</span>GRAM</span></div>
        <nav className="nav" aria-label="Main">
          <a href="#/dashboard" className={nav === "dashboard" ? "active" : ""} aria-current={nav === "dashboard" ? "page" : undefined}><span className="nav-ic">◧</span>Dashboard</a>
          <a href="#/runs" className={nav === "runs" ? "active" : ""} aria-current={nav === "runs" ? "page" : undefined}><span className="nav-ic">▶</span>Runs</a>
        </nav>
        <div className="side-foot">
          <strong>Ingram Landing Zone</strong>
          Design &amp; deploy agent <span className="mode-pill cloud">CLOUD</span>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="crumb">Ingram Agents</span><span className="sep">·</span><span>{crumb}</span>
          <span className="who">
            {email}
            <a href="/">Classic UI</a>
            <button type="button" className="btn btn-sm" onClick={onSignOut}>Sign out</button>
          </span>
        </header>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
