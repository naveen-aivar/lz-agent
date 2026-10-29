import type { ReactNode } from "react";
import type { Theme } from "../theme";
export type Nav = "dashboard" | "runs" | "new";
const ITEMS: [Nav, string, string, string][] = [
  ["dashboard", "#/dashboard", "◧", "Dashboard"],
  ["runs", "#/runs", "▶", "Runs"],
  ["new", "#/new", "+", "New run"],
];
/** App frame: sidebar, breadcrumb bar with theme switch, content. */
export function Shell({ nav, crumb, email, theme, onTheme, onSignOut, children }: {
  nav: Nav; crumb: string; email?: string; theme: Theme; onTheme: (t: Theme) => void; onSignOut: () => void; children: ReactNode;
}) {
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand"><span className="brand-logo"><span className="in">IN</span>GRAM</span></div>
        <nav className="nav" aria-label="Main">
          {ITEMS.map(([id, href, icon, label]) => (
            <a key={id} href={href} className={nav === id ? "active" : ""} aria-current={nav === id ? "page" : undefined}><span className="nav-ic">{icon}</span>{label}</a>
          ))}
        </nav>
        <div className="side-foot">
          <strong>Ingram Landing Zone</strong>
          Design &amp; deploy agent
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="crumb">Ingram Agents</span><span className="sep">·</span><span>{crumb}</span>
          <span className="who">
            {email}
            <button type="button" className="btn btn-sm" aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} onClick={() => onTheme(theme === "dark" ? "light" : "dark")}>
              {theme === "dark" ? "☀ Light" : "☾ Dark"}
            </button>
            <button type="button" className="btn btn-sm" onClick={onSignOut}>Sign out</button>
          </span>
        </header>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
