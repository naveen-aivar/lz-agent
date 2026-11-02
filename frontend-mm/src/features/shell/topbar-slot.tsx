'use client';

import { createContext, useContext, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

type Slot = { element: HTMLElement | null; setElement: (element: HTMLElement | null) => void };
const Ctx = createContext<Slot | null>(null);

/** Holds the place in the top bar where an agent's screen can put its own actions (a Refresh button, an account picker). */
export function TopbarSlotProvider({ children }: { children: ReactNode }) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  return <Ctx.Provider value={{ element, setElement }}>{children}</Ctx.Provider>;
}

/** The top bar draws this at its right. */
export function TopbarSlotTarget() {
  const slot = useContext(Ctx);
  return <div ref={slot?.setElement} className="flex flex-wrap items-center justify-end gap-2" />;
}

/** An agent's screen puts content at the right of the top bar with this: <TopbarActions><Button>Refresh</Button></TopbarActions>. */
export function TopbarActions({ children }: { children: ReactNode }) {
  const slot = useContext(Ctx);
  return slot?.element ? createPortal(children, slot.element) : null;
}
