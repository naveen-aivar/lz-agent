import { useEffect, useState } from "react";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { ChevronDown, Download } from "lucide-react";
import { api, imageUrl, saveFile } from "../api.js";
import { showToast } from "../toast.jsx";
import { size } from "../format.js";
import { Modal } from "./ui/Modal.jsx";
import { Notice } from "./ui/Notice.jsx";
import { Skeleton } from "./ui/Skeleton.jsx";

// Loads one output file of a run: { data, error } (data is the API's {content_type, encoding, data}). With no name it
// does nothing. Files are cached by api.file, so switching tabs does not fetch again.
export function useFile(runId, query, name) {
  const [state, setState] = useState({ data: null, error: null });
  const key = name ? `${runId}?${JSON.stringify(query)}/${name}` : null;
  useEffect(() => {
    if (!key) { setState({ data: null, error: null }); return undefined; }
    let live = true;
    setState({ data: null, error: null });
    api.file(runId, query, name).then((data) => { if (live) setState({ data, error: null }); })
      .catch((e) => { if (live) setState({ data: null, error: e.message }); });
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return state;
}

// The run's files for download, as one "Download" menu: list is [[name, label]], files is {name: bytes}; only the
// files that exist are offered. `prefix` names the saved file. The menu is drawn inside <main>.
export function DownloadMenu({ runId, files, list, query, prefix }) {
  const items = list.filter(([n]) => files && files[n]);
  if (!items.length) return null;
  const get = async (name, label) => {
    try { saveFile(await api.file(runId, query, name), `${prefix}-${name}`); } catch (e) {
      showToast({ title: `Could not download ${label}.`, description: e.message, variant: "danger" });
    }
  };
  return (
    <Menu.Root modal={false}>
      <Menu.Trigger asChild>
        <button type="button" className="btn btn-secondary btn-sm"><Download size={16} aria-hidden /> Download <ChevronDown size={14} aria-hidden /></button>
      </Menu.Trigger>
      <Menu.Portal container={document.getElementById("content")}>
        <Menu.Content align="end" sideOffset={6} collisionPadding={12} className="menu">
          {items.map(([name, label]) => (
            <Menu.Item key={name} className="menu-item" onSelect={() => get(name, label)}>
              <span className="menu-label">{label}</span><span className="menu-meta">{size(files[name])}</span>
            </Menu.Item>
          ))}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}

// A diagram picture from the run's files: the first of `names` that exists (PNG before SVG). Click it to see it larger.
// `missing` is what to say when none exists. The frame keeps its height while the picture loads.
export function DiagramImage({ runId, query, names, files, alt, missing }) {
  const name = names.find((n) => files && files[n]);
  const file = useFile(runId, query, name);
  const [zoom, setZoom] = useState(false);
  if (!name) return <div className="diagram-frame diagram-empty"><p className="tone-muted">{missing}</p></div>;
  if (file.error) return <div className="diagram-frame diagram-empty"><Notice tone="danger" title="We could not load the picture.">{file.error}</Notice></div>;
  if (!file.data) return <div className="diagram-frame"><Skeleton className="diagram-skel" /></div>;
  const src = imageUrl(file.data, name);
  return (
    <>
      <button type="button" className="diagram-frame diagram-zoom animate-fade-in" onClick={() => setZoom(true)} aria-label={`${alt}: see it larger`}>
        <img src={src} alt={alt} />
      </button>
      <Modal open={zoom} onOpenChange={setZoom} title={alt} size="xl">
        <div className="diagram-large"><img src={src} alt={alt} /></div>
      </Modal>
    </>
  );
}
