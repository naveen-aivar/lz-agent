import { useRef, useState } from "react";
import { Info } from "lucide-react";
import { Modal } from "./Modal.jsx";
import { Button } from "./Button.jsx";

// Blank-line separated paragraphs, with single line breaks kept inside a paragraph (the status legend uses them).
const paragraphs = (text) => String(text || "").split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);

// The "i" beside a label. A click (or Enter) opens a small dialog that explains it in plain words. Give it either
// { what, why, example } (shown under "What it is", "Why it matters" and "For example") or a plain `text`.
// `label` completes "About ___" for the dialog title and for screen readers.
export default function InfoHint({ label, text, what, why, example }) {
  const [open, setOpen] = useState(false);
  const button = useRef(null);
  const sections = what
    ? [["What it is", what], ["Why it matters", why], ["For example", example]].filter(([, body]) => body)
    : [[null, text]];

  // The dialog sits inside whatever holds the "i" (a tile, a table heading, a form row) in React's tree, so a click in
  // it must not reach that parent. `display: contents` keeps the wrapper out of the layout.
  return (
    <span className="info-hint-wrap" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      <button ref={button} type="button" className="info-hint" aria-label={`About ${label}`} aria-haspopup="dialog" aria-expanded={open}
        onClick={(e) => { e.preventDefault(); setOpen(true); }}>
        <Info size={14} aria-hidden />
      </button>
      <Modal open={open} onOpenChange={setOpen} title={`About ${label}`} size="md"
        onCloseAutoFocus={(e) => { e.preventDefault(); button.current?.focus(); }}
        footer={<Button onClick={() => setOpen(false)}>Got it</Button>}>
        <div className="info-sections">
          {sections.map(([title, body]) => (
            <section key={title || "text"} className="info-section">
              {title ? <h3 className="info-section-title">{title}</h3> : null}
              {paragraphs(body).map((p) => <p key={p} className="info-text">{p}</p>)}
            </section>
          ))}
        </div>
      </Modal>
    </span>
  );
}
