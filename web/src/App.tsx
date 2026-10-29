import { useCallback, useEffect, useMemo, useState } from "react";
import { canAnswerTransform, clearToken, decodeJwt, exchangeCode, isExpired, login, logout, storedToken } from "./auth";
import type { Claims } from "./auth";
import { createClient } from "./api/client";
import { loadConfig } from "./config";
import type { Config } from "./config";
import { DashboardPage } from "./components/DashboardPage";
import { NewRunPage } from "./components/NewRunPage";
import { RunRoute } from "./components/RunRoute";
import { RunsPage } from "./components/RunsPage";
import { Shell } from "./components/Shell";
import { applyTheme, initialTheme } from "./theme";
import type { Theme } from "./theme";
import { ErrorBoundary } from "./ui/ErrorBoundary";
import { ToastProvider } from "./ui/Toasts";

type Route = { page: "dashboard" | "runs" | "run" | "new"; runId: string | null; step: string | null };
const routeOf = (): Route => {
  const m = location.hash.match(/^#\/run\/([0-9a-f]+)(?:\/([a-z]+))?$/);
  if (m) return { page: "run", runId: m[1]!, step: m[2] ?? null };
  if (location.hash === "#/new") return { page: "new", runId: null, step: null };
  return { page: location.hash === "#/runs" ? "runs" : "dashboard", runId: null, step: null };
};

export function App() {
  const [cfg, setCfg] = useState<Config | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [booting, setBooting] = useState(true);
  const [route, setRoute] = useState(routeOf());
  const [runCrumb, setRunCrumb] = useState("");
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => applyTheme(theme), [theme]);

  useEffect(() => {
    const onHash = () => setRoute(routeOf());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const c = await loadConfig();
        setCfg(c);
        const code = new URLSearchParams(location.search).get("code");
        let t = code ? await exchangeCode(c, code) : storedToken();
        if (code) history.replaceState({}, "", location.pathname + location.hash);
        if (t && isExpired(decodeJwt(t))) {
          clearToken();
          t = null;
          setNotice("Your session expired. Sign in again to continue.");
        }
        setToken(t);
      } catch (e) {
        setNotice(e instanceof Error ? e.message : String(e));
      } finally {
        setBooting(false);
      }
    })();
  }, []);

  const expire = useCallback(() => {
    clearToken();
    setToken(null);
    setNotice("Your session expired. Sign in again to continue.");
  }, []);

  const api = useMemo(
    () => (cfg ? createClient({ apiUrl: cfg.apiUrl, getToken: storedToken, onExpired: expire }) : null),
    [cfg, expire],
  );
  const claims: Claims = useMemo(() => (token ? decodeJwt(token) : {}), [token]);

  if (booting) return <p>Loading…</p>;
  if (!cfg || !api || !token) {
    return (
      <main className="gate">
        <h1>Landing Zone Agent</h1>
        {notice && <p role="alert" className="error">{notice}</p>}
        {cfg && <button type="button" className="btn btn-primary" onClick={() => void login(cfg)}>Sign in</button>}
      </main>
    );
  }
  const crumbs = { dashboard: "Dashboard", runs: "Projects", new: "New project", run: runCrumb || "Project" };
  const open = (id: string) => { location.hash = `#/run/${id}`; };
  return (
    <ToastProvider>
      <Shell nav={route.page === "run" ? "runs" : route.page} crumb={crumbs[route.page]} email={claims.email} theme={theme} onTheme={setTheme} onSignOut={() => logout(cfg)}>
        <ErrorBoundary key={`${route.page}:${route.runId}`}>
          {route.page === "run" && route.runId ? (
            <RunRoute key={route.runId} runId={route.runId} step={route.step} api={api} canAnswer={canAnswerTransform(claims)} userSub={claims.sub ?? ""}
              theme={theme} onCrumb={setRunCrumb} onStep={(designId, step) => { location.hash = `#/run/${designId}/${step}`; }} />
          ) : route.page === "runs" ? (
            <RunsPage api={api} />
          ) : route.page === "new" ? (
            <NewRunPage api={api} onStarted={open} />
          ) : (
            <DashboardPage api={api} />
          )}
        </ErrorBoundary>
      </Shell>
    </ToastProvider>
  );
}
