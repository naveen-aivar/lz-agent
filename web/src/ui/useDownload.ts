import { useCallback } from "react";
import type { ArtifactName, Client } from "../api/client";
import { useToast } from "./Toasts";
/** Fetches a short-lived download link for an artifact and starts the download; a failure is shown, not hidden. */
export function useDownload(api: Pick<Client, "getArtifact">) {
  const toast = useToast();
  return useCallback(async (runId: string, name: ArtifactName) => {
    try {
      const { url, filename } = await api.getArtifact(runId, name);
      if (!url) throw new Error("the API returned no download link");
      const a = Object.assign(document.createElement("a"), { href: url, download: filename ?? "" });
      document.body.appendChild(a); a.click(); a.remove();
      toast("Download started");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "bad");
    }
  }, [api, toast]);
}
