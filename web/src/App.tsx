import { useCallback, useEffect, useMemo, useState } from "react";
import { canAnswerTransform, clearToken, decodeJwt, exchangeCode, isExpired, login, logout, storedToken } from "./auth";
import type { Claims } from "./auth";
import { createClient } from "./api/client";
import { loadConfig } from "./config";
import type { Config } from "./config";
import { RunPage } from "./components/RunPage";
import { RunsPage } from "./components/RunsPage";

const routeOf = (): { runId: string | null } => ({ runId: (location.hash.match(/^#\/run\/([0-9a-f]+)$/) ?? [])[1] ?? null });

export function App() {
  const [cfg, setCfg] = useState<Config | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [booting, setBooting] = useState(true);
  const [route, setRoute] = useState(routeOf());

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
  return (
    <>
      <header className="top">
        <a href="#/runs" onClick={() => (location.hash = "#/runs")}>Landing Zone Agent</a>
        <span>{claims.email}</span>
        <a href="/">Classic UI</a>
        <button type="button" className="btn btn-sm" onClick={() => logout(cfg)}>Sign out</button>
      </header>
      <main>
        {route.runId ? (
          <RunPage runId={route.runId} api={api} canAnswer={canAnswerTransform(claims)} userSub={claims.sub ?? ""} />
        ) : (
          <RunsPage api={api} onOpen={(id) => (location.hash = `#/run/${id}`)} />
        )}
      </main>
    </>
  );
}
