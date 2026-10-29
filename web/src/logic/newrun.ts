import { slug } from "./runs";

export const SOW_EXTENSIONS = ["pdf", "docx", "txt", "md"] as const;
export const MAX_SOW_BYTES = 10 * 1024 * 1024;

export interface NewRunInput { customer: string; requirements: string; file: { name: string; size: number } | null }

/** The error to show before anything is sent, or null when the form is good. */
export function newRunError(i: NewRunInput): string | null {
  if (slug(i.customer).length < 3) return "Enter the customer's name (at least 3 letters or numbers).";
  if (!i.file && !i.requirements.trim()) return "Add the SOW file, or type the requirements.";
  if (i.file) {
    const ext = i.file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!(SOW_EXTENSIONS as readonly string[]).includes(ext)) return "This file type isn't supported. Use PDF, DOCX, TXT or Markdown.";
    if (i.file.size > MAX_SOW_BYTES) return "This file is larger than 10 MB. Split it or upload the relevant sections.";
  }
  return null;
}

export interface PresignedPost { url: string; fields: Record<string, string> }

export function isPresignedPost(v: unknown): v is PresignedPost {
  const o = v as PresignedPost | null;
  return !!o && typeof o.url === "string" && !!o.fields && typeof o.fields === "object";
}

/** Uploads the SOW with the presigned POST the API returned. Throws naming the HTTP status on failure. */
export async function uploadSow(upload: PresignedPost, file: Blob, fetchImpl: typeof fetch = fetch): Promise<void> {
  const body = new FormData();
  for (const [k, v] of Object.entries(upload.fields)) body.append(k, v);
  body.append("file", file);  // the file field must come last
  const r = await fetchImpl(upload.url, { method: "POST", body });
  if (!r.ok) throw new Error(`The upload failed (HTTP ${r.status}). Try again.`);
}
