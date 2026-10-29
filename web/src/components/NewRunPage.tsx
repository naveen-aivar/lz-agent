import { useRef, useState } from "react";
import type { DragEvent } from "react";
import type { Client } from "../api/client";
import { MAX_SOW_BYTES, SOW_EXTENSIONS, isPresignedPost, newRunError, uploadSow } from "../logic/newrun";
import { slug } from "../logic/runs";
const size = (n: number): string => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);
/** Start a design run: customer name, the SOW file and/or typed requirements. */
export function NewRunPage({ api, onStarted }: { api: Pick<Client, "createRun" | "startRun">; onStarted: (runId: string) => void }) {
  const [customer, setCustomer] = useState("");
  const [requirements, setRequirements] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [touched, setTouched] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const problem = newRunError({ customer, requirements, file });
  function drop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files[0];
    if (f) setFile(f);
  }
  async function submit() {
    setTouched(true);
    if (problem) return;
    setError("");
    try {
      setBusy("Creating the run…");
      const created = await api.createRun({ customerId: slug(customer), requirements: requirements.trim() || undefined, fileName: file?.name });
      if (file) {
        if (!isPresignedPost(created.upload)) throw new Error("The API returned no upload link for the SOW file.");
        setBusy("Uploading the SOW…");
        await uploadSow(created.upload, file);
      }
      setBusy("Starting the analysis…");
      await api.startRun(created.runId);
      onStarted(created.runId);
    } catch (e) {
      setBusy("");
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  return (
    <>
      <h1 className="page-title">New project</h1>
      <p className="page-sub">Upload the customer's statement of work. The agent reads it, designs the landing zone, and generates and checks the Terraform and CloudFormation. Then you review the design and deploy it, all from one page.</p>
      <form className="panel panel-pad form" onSubmit={(e) => { e.preventDefault(); void submit(); }} noValidate>
        <label>Customer name
          <input value={customer} onChange={(e) => setCustomer(e.target.value)} placeholder="Moon Trades" autoFocus aria-describedby="cust-hint" />
          <span id="cust-hint" className="hint">{slug(customer).length >= 3 ? <>Run name: <code>{slug(customer)}</code></> : "Used to name the run."}</span>
        </label>
        <div
          className={`drop${drag ? " drag" : ""}${file ? " has" : ""}`} role="button" tabIndex={0}
          aria-label="Choose the SOW file"
          onClick={() => input.current?.click()} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={drop}>
          {file ? <><strong>{file.name}</strong><span className="hint">{size(file.size)} · click to change</span></>
            : <><strong>Drop the SOW here, or click to choose</strong><span className="hint">{SOW_EXTENSIONS.join(", ").toUpperCase()} up to {MAX_SOW_BYTES / 1024 / 1024} MB</span></>}
          <input ref={input} type="file" hidden accept={SOW_EXTENSIONS.map((x) => `.${x}`).join(",")} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
        {file && <button type="button" className="btn-link" onClick={() => setFile(null)}>Remove the file</button>}
        <details open={!!requirements}><summary>Add requirements that aren't in the file</summary>
          <textarea value={requirements} onChange={(e) => setRequirements(e.target.value)} placeholder="Anything the customer asked for outside the document." aria-label="Requirements" style={{ marginTop: 8 }} />
        </details>
        {touched && problem && <p className="errtext" role="alert">{problem}</p>}
        {error && <p className="errtext" role="alert">{error}</p>}
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={!!busy}>{busy || "Start the analysis"}</button>
          <a className="btn" href="#/dashboard">Cancel</a>
        </div>
      </form>
    </>
  );
}
