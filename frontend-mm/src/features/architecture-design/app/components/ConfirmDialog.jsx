import { useState } from "react";
import { showToast } from "../toast.jsx";
import { Button } from "./ui/Button.jsx";
import { Modal } from "./ui/Modal.jsx";
import { Notice } from "./ui/Notice.jsx";

// Asks before an action that starts work or records a decision: a title, one sentence, one main button. While the
// action runs the button shows a spinner; a failure stays in the dialog and is toasted too.
//   confirm: { title, text, label, run: async () => successMessage | undefined, failTitle }
export default function ConfirmDialog({ confirm, onClose }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  if (!confirm) return null;
  const go = async () => {
    setBusy(true); setErr(null);
    try {
      const msg = await confirm.run();
      if (msg) showToast(typeof msg === "string" ? { title: msg } : msg);
      onClose();
    } catch (e) {
      setErr(e.message);
      showToast({ title: confirm.failTitle || "That did not work.", description: e.message, variant: "danger" });
    } finally { setBusy(false); }
  };
  return (
    <Modal open onOpenChange={(o) => { if (!o && !busy) onClose(); }} title={confirm.title} description={confirm.text}
      footer={<><Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button><Button loading={busy} onClick={go}>{confirm.label}</Button></>}>
      {err ? <Notice tone="danger" title={confirm.failTitle || "That did not work."}>{err}</Notice> : null}
    </Modal>
  );
}
