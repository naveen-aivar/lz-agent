import { useRef, useState } from "react";
import { ArrowRight, FileText, History, Upload, X } from "lucide-react";
import { api, toBase64 } from "../api.js";
import { sampleRun } from "../sampleRun.js";
import { INFO } from "../info.js";
import { FILE_EXT, MAX_FILE_BYTES, MAX_TEXT, MIN_TEXT, size } from "../format.js";
import { showToast } from "../toast.jsx";
import { navigate } from "../useRoute.js";
import ConfirmDialog from "../components/ConfirmDialog.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Card } from "../components/ui/Card.jsx";
import { Field } from "../components/ui/Field.jsx";
import InfoHint from "../components/ui/InfoHint.jsx";
import { Notice } from "../components/ui/Notice.jsx";
import { PageHeader } from "../components/ui/PageHeader.jsx";

const ACCEPT = ".md,.markdown,.txt,.docx,.pdf,text/markdown,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

// The requirements in, the landing zone first. Left: the form (title, the SRS as text or a file) and its one button,
// which asks before it starts. Right: the two samples (example requirements, or the saved sample run played back).
export default function NewArchitecture() {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState(null);
  const [fileErr, setFileErr] = useState(null);
  const [over, setOver] = useState(false);
  const [sampleText, setSampleText] = useState(null);   // the saved sample run's SRS while it is in the form
  const [confirm, setConfirm] = useState(null);
  const input = useRef(null);

  const ready = !!file || text.trim().length >= MIN_TEXT;
  const filled = !!(file || text || title);
  const isSampleRun = !file && sampleText !== null && text === sampleText;

  const pick = (f) => {
    if (!f) return;
    const ext = (f.name.split(".").pop() || "").toLowerCase();
    if (!FILE_EXT.includes(ext)) { setFileErr("Upload a .md, .txt, .docx or .pdf file."); return; }
    if (f.size > MAX_FILE_BYTES) { setFileErr(`${f.name} is ${size(f.size)}; files up to 4 MB.`); return; }
    setFileErr(null);
    setFile(f);
  };
  const clear = () => { setFile(null); setText(""); setTitle(""); setFileErr(null); setSampleText(null); };

  const useSample = async () => {
    try {
      const resp = await fetch("/agents/architecture-design/sample_srs.md");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setFile(null);
      setText(await resp.text());
      if (!title) setTitle("Sample: billing dispute assistant");
      setSampleText(null);
      showToast({ title: "Sample requirements loaded." });
    } catch (e) { showToast({ title: "Could not load the sample.", description: e.message, variant: "danger" }); }
  };
  const useSampleRun = async () => {
    try {
      const s = await sampleRun.srs();
      setFile(null);
      setText(s.text);
      setTitle(s.title);
      setSampleText(s.text);
      showToast({ title: "Sample run loaded.", description: "Starting it plays the recorded run back, with no model calls." });
    } catch (e) { showToast({ title: "Could not load the sample.", description: e.message, variant: "danger" }); }
  };

  const start = async () => {
    if (isSampleRun) {
      await sampleRun.begin();
      await new Promise((resolve) => setTimeout(resolve, 600));
      setSampleText(null);
      navigate("runs", sampleRun.id);
      return { title: "Sample run started.", description: "The landing zone comes first." };
    }
    const body = { title: title.trim() };
    if (file) body.file = { name: file.name, content_base64: await toBase64(file) };
    else body.srs_text = text;
    const res = await api.start(body);
    window.dispatchEvent(new Event("quota:changed"));
    navigate("runs", res.run_id);
    return { title: "Started: the landing zone comes first.", description: "You can leave this page and come back." };
  };
  const ask = () => setConfirm({
    title: "Design the landing zone?",
    text: isSampleRun ? "The saved sample run plays back step by step. It makes no model calls."
      : "The agent designs the landing zone from these requirements and draws it (1 to 3 model calls, a few minutes). You approve it before the design starts.",
    label: "Start", failTitle: "Not started.", run: start,
  });

  return (
    <>
      <PageHeader title="New architecture" description="Add the software requirements. The landing zone comes first; you approve each step." />
      <div className="split split-wide">
        <Card title="Requirements" info={INFO.requirements}>
          <form className="stack-sm" noValidate onSubmit={(e) => { e.preventDefault(); if (ready) ask(); }}>
            <Field id="title" label="Title" optional>
              <input id="title" className="input" type="text" maxLength={200} autoComplete="off" placeholder="Billing dispute assistant"
                value={title} onChange={(e) => setTitle(e.target.value)} />
            </Field>
            <Field id="srs" label="Requirements" hint={file ? "The file is used instead of the text." : `${text.length.toLocaleString()} / ${MAX_TEXT.toLocaleString()} characters`}>
              <textarea id="srs" className="textarea srs-text" rows={12} maxLength={MAX_TEXT} disabled={!!file}
                placeholder="Paste the SRS: goals, users, functional and non-functional requirements, constraints, integrations…"
                value={text} onChange={(e) => setText(e.target.value)} />
            </Field>
            {file ? (
              <div className="file-row animate-fade-in">
                <FileText size={18} aria-hidden className="tone-info" />
                <span className="file-name">{file.name}</span>
                <span className="tone-muted">{size(file.size)}</span>
                <button type="button" className="icon-btn" onClick={() => setFile(null)} aria-label={`Remove ${file.name}`}><X size={16} aria-hidden /></button>
              </div>
            ) : (
              <div className={`drop${over ? " is-over" : ""}`}
                onDragEnter={(e) => { e.preventDefault(); setOver(true); }} onDragOver={(e) => { e.preventDefault(); setOver(true); }}
                onDragLeave={(e) => { e.preventDefault(); setOver(false); }}
                onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files[0]); }}>
                <Upload size={18} aria-hidden className="tone-muted" />
                <span><button type="button" className="link-btn" onClick={() => input.current?.click()}>Upload a file</button> or drop it here</span>
                <span className="tone-muted">.md, .txt, .docx or .pdf, up to 4 MB</span>
                <input ref={input} className="sr-only" type="file" accept={ACCEPT} tabIndex={-1} aria-label="Upload a requirements file"
                  onChange={(e) => { pick(e.target.files[0]); e.target.value = ""; }} />
              </div>
            )}
            {fileErr ? <Notice tone="danger">{fileErr}</Notice> : null}
            <div className="form-actions">
              <Button variant="tertiary" onClick={clear} disabled={!filled}>Clear</Button>
              <Button type="submit" disabled={!ready}>Design the landing zone <ArrowRight size={16} aria-hidden /></Button>
            </div>
          </form>
        </Card>
        <Card title="Start from a sample" info={INFO.samples}>
          <div className="stack-sm">
            <button type="button" className="sample-pick" onClick={useSample}>
              <FileText size={20} aria-hidden className="tone-info" />
              <span><span className="pick-title">Use a sample</span><span className="pick-text">Example requirements for a billing dispute assistant, put in the form.</span></span>
            </button>
            <button type="button" className="sample-pick" onClick={useSampleRun}>
              <History size={20} aria-hidden className="tone-info" />
              <span><span className="pick-title">Sample run</span><span className="pick-text">A recorded run, played back step by step with its real outputs. No model calls.</span></span>
            </button>
            <p className="field-hint flow-note">How it works <InfoHint {...INFO.flow} /></p>
          </div>
        </Card>
      </div>
      <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />
    </>
  );
}
