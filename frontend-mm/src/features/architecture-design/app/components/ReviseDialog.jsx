import { useEffect, useState } from "react";
import { showToast } from "../toast.jsx";
import { Button } from "./ui/Button.jsx";
import { Field } from "./ui/Field.jsx";
import { Modal } from "./ui/Modal.jsx";
import { Notice } from "./ui/Notice.jsx";

// "Flags for review" (round 2, R4/R5): the points a step left for the architect. No flag ever caused a model call.
// Ticking a flag appends its suggested instruction to the instruction (one line each); unticking removes that line.
//   flags: [{ severity: "info" | "warning", area, message, suggested_instruction }]
export function FlagsReview({ idPrefix, flags, text, setText }) {
  const list = (flags || []).filter((f) => f && (f.message || f.suggested_instruction));
  if (!list.length) return null;
  const lines = () => text.split("\n");
  const has = (t) => lines().some((l) => l.trim() === t.trim());
  const toggle = (t, on) => {
    const kept = lines().filter((l) => l.trim() !== t.trim());
    if (on) kept.push(t);
    setText(kept.filter((l) => l.trim()).join("\n"));
  };
  return (
    <fieldset className="flags">
      <legend className="flags-head">Flags for review ({list.length})</legend>
      <p className="field-hint">None of these caused a model call. Tick one to add its change below.</p>
      <ul className="flag-list">
        {list.map((f, i) => {
          const id = `${idPrefix}-flag-${i}`;
          const t = f.suggested_instruction || f.message;
          return (
            <li key={id} className={`flag-item${f.severity === "warning" ? " is-warn" : ""}`}>
              <input type="checkbox" id={id} checked={has(t)} onChange={(e) => toggle(t, e.target.checked)} />
              <label htmlFor={id}>
                <span className="flag-tag">{f.severity || "info"} · {f.area || "review"}</span>
                <span>{f.message || ""}</span>
                {f.suggested_instruction ? <span className="flag-instr">Adds: {f.suggested_instruction}</span> : null}
              </label>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}

// A revision: an instruction (5+ characters), optional flags that fill it, and one button that starts the new version.
//   open, onClose, title, description, label (the button), placeholder, hint, flags, initial, tooShort, run(text) -> message
export default function ReviseDialog({ open, onClose, title, description, label, placeholder, hint, flags, initial = "", tooShort, run, idPrefix }) {
  const [text, setText] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [short, setShort] = useState(false);
  const [err, setErr] = useState(null);
  useEffect(() => { if (open) { setText(initial); setErr(null); setShort(false); } }, [open, initial]);
  const go = async () => {
    if (text.trim().length < 5) { setShort(true); return; }
    setBusy(true); setErr(null); setShort(false);
    try {
      showToast({ title: await run(text.trim()) });
      onClose();
    } catch (e) {
      setErr(`Not started: ${e.message}`);
      showToast({ title: "Not started.", description: e.message, variant: "danger" });
    } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onOpenChange={(o) => { if (!o && !busy) onClose(); }} title={title} description={description} size="lg"
      footer={<><Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button><Button loading={busy} onClick={go}>{label}</Button></>}>
      <div className="stack-sm">
        <FlagsReview idPrefix={idPrefix} flags={flags} text={text} setText={setText} />
        <Field id={`${idPrefix}-instruction`} label="What should change?" hint={hint} error={short ? tooShort : null}>
          <textarea id={`${idPrefix}-instruction`} className="textarea" rows={4} maxLength={4000} placeholder={placeholder}
            value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        {err ? <Notice tone="danger">{err}</Notice> : null}
      </div>
    </Modal>
  );
}
