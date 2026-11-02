'use client';

import { useEffect, useRef, useState } from 'react';

import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';
import { Skeleton, SkeletonText } from '@/shared/design-system/ui/skeleton';

const PDF_URL = '/agents/tco/pdfjs/pdf.min.mjs';
const WORKER_URL = '/agents/tco/pdfjs/pdf.worker.min.mjs';
const MAX_BYTES = 50 * 1024 * 1024;

interface PdfPage {
  getViewport: (options: { scale: number }) => { width: number; height: number };
  render: (options: { canvas: HTMLCanvasElement; viewport: { width: number; height: number } }) => { promise: Promise<void> };
}

interface PdfDocument {
  numPages: number;
  getPage: (number: number) => Promise<PdfPage>;
}

interface PdfJs {
  GlobalWorkerOptions: { workerSrc: string };
  getDocument: (source: { data: Uint8Array }) => { promise: Promise<PdfDocument> };
}

async function loadPdfJs(): Promise<PdfJs> {
  const lib = (await import(/* webpackIgnore: true */ PDF_URL)) as PdfJs;
  lib.GlobalWorkerOptions.workerSrc = WORKER_URL;
  return lib;
}

/** The slide deck, one slide at a time. The same preview the assessment's own screen shows. */
export function DeckPreview({ url }: { url: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const pdfRef = useRef<PdfDocument | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState('');
  const [drawing, setDrawing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError('');
    setPage(1);
    setTotal(0);
    void (async () => {
      try {
        const response = await fetch(url, { credentials: 'omit', cache: 'no-store' });
        if (!response.ok) throw new Error('Could not load the deck.');
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (bytes.byteLength > MAX_BYTES) throw new Error('The deck is too large to preview.');
        const pdfjs = await loadPdfJs();
        const pdf = await pdfjs.getDocument({ data: bytes }).promise;
        if (cancelled) return;
        pdfRef.current = pdf;
        setTotal(pdf.numPages);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : 'Could not load the deck.');
      }
    })();
    return () => {
      cancelled = true;
      pdfRef.current = null;
    };
  }, [url]);

  useEffect(() => {
    const pdf = pdfRef.current;
    const canvas = canvasRef.current;
    const stage = stageRef.current;
    if (!pdf || !canvas || !stage || total < 1) return;
    let cancelled = false;
    setDrawing(true);
    void (async () => {
      try {
        const slide = await pdf.getPage(page);
        if (cancelled) return;
        const base = slide.getViewport({ scale: 1 });
        const cssWidth = Math.min(stage.clientWidth || 720, 960);
        const ratio = window.devicePixelRatio || 1;
        const viewport = slide.getViewport({ scale: (cssWidth / base.width) * ratio });
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = '100%';
        canvas.style.height = 'auto';
        await slide.render({ canvas, viewport }).promise;
      } catch {
        if (!cancelled) setError('Could not draw this slide.');
      } finally {
        if (!cancelled) setDrawing(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [page, total, url]);

  return (
    <Card className="mt-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Slide deck</h2>
        <a className="text-sm font-medium text-[var(--color-primary-700)]" href={url} rel="noopener noreferrer">
          Download the deck
        </a>
      </div>
      {error ? <p className="mt-3 text-sm text-[var(--color-gray-500)]">{error} You can still download it.</p> : null}
      {error ? null : (
        <>
          <div ref={stageRef} className="relative mt-3 flex justify-center">
            <canvas ref={canvasRef} role="img" aria-label={total ? `Slide ${page} of ${total}` : 'Loading the slide deck'} className={`w-full rounded-[var(--radius-lg)] border border-[var(--color-gray-100)]${total ? '' : ' aspect-video'}`} />
            {/* A slide-shaped placeholder sits over the empty canvas until the deck has opened. */}
            {total ? null : <Skeleton className="absolute inset-0 h-full w-full rounded-[var(--radius-lg)]" />}
          </div>
          <div className="mt-3 flex items-center justify-between gap-3">
            <Button type="button" variant="secondary" size="sm" disabled={drawing || page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>
              Previous
            </Button>
            <p className="text-sm text-[var(--color-gray-500)]" aria-live="polite">{total ? `Slide ${page} of ${total}` : <SkeletonText>Slide 1 of 12</SkeletonText>}</p>
            <Button type="button" variant="secondary" size="sm" disabled={drawing || page >= total} onClick={() => setPage((current) => Math.min(total, current + 1))}>
              Next
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}
