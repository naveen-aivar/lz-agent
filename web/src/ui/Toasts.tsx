import { createContext, useCallback, useContext, useRef, useState } from "react";
import type { ReactNode } from "react";
type Tone = "ok" | "bad";
interface Toast { id: number; text: string; tone: Tone }
type Notify = (text: string, tone?: Tone) => void;
const Ctx = createContext<Notify | null>(null);
export function useToast(): Notify {
  const n = useContext(Ctx);
  if (!n) throw new Error("useToast needs a <ToastProvider> above it");
  return n;
}
export function ToastProvider({ children, ms = 4500 }: { children: ReactNode; ms?: number }) {
  const [items, setItems] = useState<Toast[]>([]);
  const next = useRef(1);
  const notify = useCallback<Notify>((text, tone = "ok") => {
    const id = next.current++;
    setItems((x) => [...x, { id, text, tone }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), ms);
  }, [ms]);
  return (
    <Ctx.Provider value={notify}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast toast-${t.tone}`}>{t.text}</div>)}
      </div>
    </Ctx.Provider>
  );
}
