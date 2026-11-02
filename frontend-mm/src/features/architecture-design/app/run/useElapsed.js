import { useEffect, useState } from "react";

/** Whole seconds since `startEpoch` (seconds), ticking once a second while `active`; null until there is a start. */
export function useElapsed(startEpoch, active) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active || startEpoch == null) return undefined;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active, startEpoch]);
  if (startEpoch == null) return null;
  return Math.max(0, Math.floor(now / 1000 - startEpoch));
}

/** 75 -> "1:15", 3725 -> "1:02:05". */
export function clock(seconds) {
  const s = Math.max(0, seconds ?? 0);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const two = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${two(m)}:${two(r)}` : `${m}:${two(r)}`;
}

/** True while `active`, and for `ms` after it ends: lets the finished picture stay on screen a moment before the page moves on. */
export function useLingering(active, ms = 7000) {
  const [lingering, setLingering] = useState(false);
  useEffect(() => {
    if (active) { setLingering(true); return undefined; }
    const id = setTimeout(() => setLingering(false), ms);
    return () => clearTimeout(id);
  }, [active, ms]);
  return active || lingering;
}
