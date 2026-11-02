import { useCallback, useEffect, useRef, useState } from "react";

// The top bar's Refresh asks every load on the page to run again.
export const refreshAll = () => window.dispatchEvent(new Event("app:refresh"));

// Loads once, and then again every `ms` while `active`. With `enabled: false` it does nothing at all (no request, no error).
// A failed poll keeps the last good data on screen; the error is reported only when there is nothing to show, and the
// next try waits longer (doubling, at most a minute). Polling stops when the page is left (the hook unmounts).
export function usePoll(load, { ms = 4000, active = true, enabled = true, deps = [] } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const ref = useRef(load); ref.current = load;
  const failures = useRef(0);
  const refresh = useCallback(async () => {
    try { setData(await ref.current()); setError(null); failures.current = 0; } catch (e) { setError(e.message); failures.current += 1; } finally { setLoading(false); }
  }, []);
  useEffect(() => {
    if (!enabled) { setData(null); setError(null); setLoading(false); return undefined; }
    setLoading(true); refresh();
    window.addEventListener("app:refresh", refresh);
    let id = null;
    const tick = async () => {
      await refresh();
      id = setTimeout(tick, Math.min(60000, ms * 2 ** failures.current));
    };
    if (active) id = setTimeout(tick, ms);
    return () => { clearTimeout(id); window.removeEventListener("app:refresh", refresh); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, ms, active, enabled, ...deps]);
  return { data, error, loading, refresh };
}
