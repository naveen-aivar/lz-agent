import { useEffect, useState } from "react";
import { answerKey } from "../api.js";
import { Button } from "./ui/Button.jsx";
import { Field } from "./ui/Field.jsx";
import { Modal } from "./ui/Modal.jsx";

// The deployed API asks for the shared access key (X-Access-Key). It is asked for here once, when a call is refused,
// and kept for this browser tab only. The words are the old console's.
export default function AccessKeyDialog() {
  const [ask, setAsk] = useState(null);   // null, or { wrong }
  const [key, setKey] = useState("");
  useEffect(() => {
    const on = (e) => { setKey(""); setAsk({ wrong: !!e.detail?.wrong }); };
    window.addEventListener("accesskey:ask", on);
    return () => window.removeEventListener("accesskey:ask", on);
  }, []);
  if (!ask) return null;
  const done = (value) => { answerKey(value); setAsk(null); };
  return (
    <Modal open onOpenChange={(o) => { if (!o) done(""); }} title="Access key"
      description={ask.wrong ? "That access key was not accepted. Enter the access key." : "Enter the access key for this app."}
      footer={<><Button variant="secondary" onClick={() => done("")}>Cancel</Button><Button type="submit" form="access-key-form" disabled={!key.trim()}>Continue</Button></>}>
      <form id="access-key-form" onSubmit={(e) => { e.preventDefault(); if (key.trim()) done(key); }}>
        <Field id="access-key" label="Access key" hint="Kept for this browser tab only.">
          <input id="access-key" className="input" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
        </Field>
      </form>
    </Modal>
  );
}
