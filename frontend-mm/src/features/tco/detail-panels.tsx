'use client';

import { Download, Eye, FileArchive, FileSpreadsheet, FileText, Presentation } from 'lucide-react';
import { useState } from 'react';

import { DeckPreview } from '@/features/tco/deck-preview';
import { formatDate, outputLabel, sortOutputs } from '@/features/tco/format';
import type { JobEvent, OutputFile } from '@/features/tco/api';
import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';

function fileIcon(file: OutputFile) {
  const name = file.filename.toLowerCase();
  if (file.label === 'deck_pdf' || name.endsWith('.pdf')) return FileText;
  if (file.label === 'deck' || name.endsWith('.pptx')) return Presentation;
  if (name.endsWith('.xlsx') || name.endsWith('.xls') || name.endsWith('.csv')) return FileSpreadsheet;
  if (name.endsWith('.zip') || file.label === 'bundle') return FileArchive;
  return FileText;
}

function canPreview(file: OutputFile): boolean {
  return file.label === 'deck_pdf' || file.filename.toLowerCase().endsWith('.pdf');
}

/** One card per file: the slide deck can be previewed here; every file can be downloaded. */
export function DownloadCards({ files }: { files: OutputFile[] }) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const ordered = sortOutputs(files);
  return (
    <div>
      <ul className="grid gap-3 sm:grid-cols-2">
        {ordered.map((file) => {
          const Icon = fileIcon(file);
          const previewable = canPreview(file);
          const open = previewUrl === file.url;
          return (
            <li key={file.filename}>
              <Card className="flex h-full flex-col gap-3 p-4">
                <div className="flex items-start gap-3">
                  <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[var(--color-primary-50)] text-[var(--color-primary-700)]">
                    <Icon className="h-5 w-5" />
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-[var(--color-gray-900)]">{outputLabel(file.label)}</p>
                    <p className="truncate text-xs text-[var(--color-gray-500)]">{file.filename}</p>
                  </div>
                </div>
                <div className="mt-auto flex flex-wrap gap-2">
                  {previewable ? (
                    <Button type="button" variant="secondary" size="sm" aria-expanded={open} onClick={() => setPreviewUrl(open ? null : file.url)}>
                      <Eye className="h-4 w-4" aria-hidden /> {open ? 'Hide preview' : 'Preview'}
                    </Button>
                  ) : (
                    <Button type="button" variant="secondary" size="sm" disabled>
                      <Eye className="h-4 w-4" aria-hidden /> Preview
                    </Button>
                  )}
                  <Button asChild size="sm">
                    <a href={file.url} rel="noopener noreferrer">
                      <Download className="h-4 w-4" aria-hidden /> Download
                    </a>
                  </Button>
                </div>
                {previewable ? null : (
                  <p className="text-xs text-[var(--color-gray-500)]">Preview is available for the slide deck. Download this file to open it.</p>
                )}
              </Card>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-sm text-[var(--color-gray-500)]">These links last a few minutes. Refresh the page if one has expired.</p>
      {previewUrl ? <DeckPreview url={previewUrl} /> : null}
    </div>
  );
}

/** A vertical line through the dots, and each step in its own card. */
function SentValues({ sent }: { sent?: Record<string, unknown> | null }) {
  const entries = sent && typeof sent === 'object' ? Object.entries(sent) : [];
  if (!entries.length) return null;
  return (
    <ul className="mt-1 list-disc pl-5 text-sm" aria-label="Sent to AWS Transform">
      {entries.map(([key, value]) => (
        <li key={key}><span className="text-[var(--color-gray-500)]">{key}: </span>{String(value)}</li>
      ))}
    </ul>
  );
}
export function ActivityTimeline({ events, running }: { events: JobEvent[]; running: boolean }) {
  if (!events.length && !running) {
    return <p className="text-sm text-[var(--color-gray-500)]">No activity yet.</p>;
  }
  return (
    <ol className="tco-timeline" aria-label="What the assessment has done">
      {events.map((event, index) => (
        <li key={`${event.ts}-${index}`} className="tco-timeline-item animate-fade-up" style={{ ['--stagger' as string]: Math.min(index, 8) }}>
          <span className="tco-timeline-dot" aria-hidden />
          <div className="tco-timeline-card">
            <time className="text-xs text-[var(--color-gray-500)]" dateTime={event.ts}>{formatDate(event.ts)}</time>
            <p className="mt-1 text-sm text-[var(--color-gray-900)]">{event.message}</p>
            <SentValues sent={event.detail?.sent} />
          </div>
        </li>
      ))}
      {running ? (
        <li className="tco-timeline-item">
          <span className="tco-timeline-dot tco-timeline-dot-wait" aria-hidden />
          <div className="tco-timeline-card">
            <p className="text-sm text-[var(--color-gray-500)]">Choosing the next step.</p>
          </div>
        </li>
      ) : null}
    </ol>
  );
}
