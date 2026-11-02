'use client';

import { Download, Eye } from 'lucide-react';
import { useEffect, useState } from 'react';
import { orchestratorApi, type DeckFiles, type DeckResult, type Run } from '@/features/orchestrator/api';
import { messageOf, toneOf } from '@/features/orchestrator/run-list';
import { deckName, isFinished, RUN_LABELS, SLIDE_LABELS, sourceName } from '@/features/orchestrator/trigger';
import { DeckPreview } from '@/features/tco/deck-preview';
import { formatDate } from '@/features/tco/format';
import { Notice } from '@/shared/components/notice';
import { PageHeader } from '@/shared/components/page-header';
import { Badge } from '@/shared/design-system/ui/badge';
import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';

const POLL_MS = 3000;

function slideTone(status: string): 'success' | 'warning' | 'danger' | 'muted' {
  if (status === 'built' || status === 'code') return 'success';
  if (status === 'failed') return 'danger';
  return status === 'unavailable' ? 'warning' : 'muted';
}

/** One finished deck: preview the PDF, download the PowerPoint, and see how each slide came out. */
function DeckCard({ result, files }: { result?: DeckResult; files?: DeckFiles }) {
  const [open, setOpen] = useState(false);
  const pdf = files?.files.pdf;
  const pptx = files?.files.pptx;
  const name = result?.name ?? files?.name ?? '';
  const slides = result?.slides ?? [];
  const problems = slides.filter((slide) => slide.status === 'unavailable' || slide.status === 'failed');
  return (
    <Card className="mt-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{name}</h2>
          <p className="text-sm text-[var(--color-gray-500)]">
            {slides.length} slides{problems.length ? `, ${problems.length} without data or not built` : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {pdf ? (
            <Button type="button" variant="secondary" size="sm" aria-expanded={open} onClick={() => setOpen(!open)}>
              <Eye className="h-4 w-4" aria-hidden /> {open ? 'Hide preview' : 'Preview'}
            </Button>
          ) : null}
          {pptx ? (
            <Button asChild size="sm">
              <a href={pptx.url} rel="noopener noreferrer"><Download className="h-4 w-4" aria-hidden /> Download PowerPoint</a>
            </Button>
          ) : null}
          {pdf ? (
            <Button asChild variant="secondary" size="sm">
              <a href={pdf.url} rel="noopener noreferrer"><Download className="h-4 w-4" aria-hidden /> Download PDF</a>
            </Button>
          ) : null}
        </div>
      </div>
      {open && pdf ? <DeckPreview url={pdf.url} /> : null}
      {(result?.warnings ?? []).map((warning) => <p key={warning} className="mt-2 text-sm text-[var(--color-warning-700)]">{warning}</p>)}
      {slides.length ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm font-medium">Slides</summary>
          <table className="mt-2 w-full text-left text-sm">
            <caption className="sr-only">{name} slides</caption>
            <tbody>
              {slides.map((slide) => (
                <tr key={`${slide.no}-${slide.title}`} className="border-t border-[var(--color-gray-100)]">
                  <td className="w-12 py-1.5 text-[var(--color-gray-500)]">{slide.no}</td>
                  <td className="py-1.5 pr-3">{slide.title}{slide.reason ? <span className="text-[var(--color-gray-500)]"> · {slide.reason}</span> : null}</td>
                  <td className="py-1.5 text-right"><Badge variant={slideTone(slide.status)}>{SLIDE_LABELS[slide.status] ?? slide.status}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}
    </Card>
  );
}

/** One run: progress while it builds, then each finished deck. */
export function RunDetail({ id }: { id: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const [files, setFiles] = useState<DeckFiles[]>([]);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'decks' | 'timeline'>('decks');

  useEffect(() => {
    let stop = false;
    let timer = 0;
    const loop = async () => {
      try {
        const next = await orchestratorApi.getRun(id);
        if (stop) return;
        setRun(next);
        setError('');
        if (next.status === 'COMPLETED') {
          const outputs = await orchestratorApi.outputs(id);
          if (!stop) setFiles(outputs.decks);
        }
        if (isFinished(next.status)) return;
      } catch (caught) {
        if (stop) return;
        setError(messageOf(caught));
      }
      timer = window.setTimeout(() => void loop(), POLL_MS);
    };
    void loop();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [id]);

  if (error && !run) return <Notice tone="danger" title="This run could not be opened." className="mt-4"><p>{error}</p></Notice>;
  if (!run) return <p className="mt-4 text-sm text-[var(--color-gray-500)]" aria-live="polite">Loading.</p>;

  const finished = isFinished(run.status);
  const problems = Object.entries(run.input_problems ?? {});
  return (
    <div className="view-enter">
      <PageHeader
        title={run.customer || 'Decks'}
        description={`${run.decks.map(deckName).join(' and ')} · Created ${formatDate(run.created_at)}${run.updated_at ? ` · Updated ${formatDate(run.updated_at)}` : ''}`}
        meta={<Badge variant={toneOf(run.status)}>{run.stalled && !finished ? 'Stalled' : (RUN_LABELS[run.status] ?? run.status)}</Badge>}
      />
      {run.source_jobs && Object.keys(run.source_jobs).length ? (
        <p className="mt-2 break-all text-xs text-[var(--color-gray-500)]">
          Built from: {Object.entries(run.source_jobs).map(([source, id]) => `${sourceName(source)} ${id}`).join(' · ')}
        </p>
      ) : null}
      {!finished ? (
        <p className="mt-3 text-sm text-[var(--color-gray-700)]" aria-live="polite">
          {run.stalled ? 'This run has not reported for a while. Start it again from the list if it does not move.' : 'The decks are being written. This takes about 5 to 10 minutes and updates by itself.'}
        </p>
      ) : null}
      {run.status === 'FAILED' ? (
        <Notice tone="danger" title="The decks could not be built." className="mt-4"><p>{run.error?.message || 'The run stopped before the decks were ready.'}</p></Notice>
      ) : null}
      {problems.length ? (
        <Notice tone="warning" title="Some files were not used." className="mt-4">
          <ul className="list-disc pl-5">{problems.map(([source, why]) => <li key={source}>{source}: {why}</li>)}</ul>
        </Notice>
      ) : null}
      <div role="tablist" aria-label="Run sections" className="mb-2 mt-4 flex gap-2">
        {(['decks', 'timeline'] as const).map((name) => (
          <button key={name} type="button" role="tab" aria-selected={tab === name} className={`rounded-full px-3 py-1.5 text-sm ${tab === name ? 'bg-[var(--color-primary-50)] font-medium text-[var(--color-primary-700)]' : 'text-[var(--color-gray-700)]'}`} onClick={() => setTab(name)}>
            {name === 'decks' ? 'Decks' : 'Timeline'}
          </button>
        ))}
      </div>
      {tab === 'decks' ? (
        run.status === 'COMPLETED' ? (
          (run.results ?? []).map((result) => <DeckCard key={result.deck} result={result} files={files.find((item) => item.deck === result.deck)} />)
        ) : (
          <p className="text-sm text-[var(--color-gray-500)]">{run.status === 'FAILED' ? 'There are no decks because the run failed.' : 'The decks appear here when they are ready. Download links last 15 minutes; reload the page for new ones.'}</p>
        )
      ) : (
        <ol className="grid gap-2" aria-label="What the run has done">
          {(run.events ?? []).map((event, index) => (
            <li key={`${event.ts}-${index}`} className="rounded-[var(--radius-md)] border border-[var(--color-gray-200)] px-3 py-2">
              <time className="text-xs text-[var(--color-gray-500)]" dateTime={event.ts}>{formatDate(event.ts)}</time>
              <p className="mt-0.5 text-sm">{event.message}</p>
            </li>
          ))}
          {!(run.events ?? []).length ? <li className="text-sm text-[var(--color-gray-500)]">No activity yet.</li> : null}
        </ol>
      )}
    </div>
  );
}
