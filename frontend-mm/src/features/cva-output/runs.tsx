'use client';

import { useEffect, useState } from 'react';

import { ApiError, cvaRequest, fileToB64 } from '@/features/cva-output/api';
import { NameField, useActor } from '@/features/cva-output/actor';
import { PackageMark } from '@/features/cva-output/package-mark';
import type { CvaRunRow } from '@/features/cva-output/types';
import type { Navigate } from '@/features/agents/types';
import { controlClass } from '@/shared/components/form-controls';
import { Notice } from '@/shared/components/notice';
import { PageHeader } from '@/shared/components/page-header';
import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';
import { Skeleton } from '@/shared/design-system/ui/skeleton';
import { useToast } from '@/shared/design-system/ui/toaster';

const SKELETON_ROWS = 15;

export function RunsScreen({ navigate }: { navigate: Navigate }) {
  const toast = useToast();
  const [rows, setRows] = useState<CvaRunRow[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    cvaRequest<{ runs: CvaRunRow[] }>('/runs')
      .then((page) => { if (live) setRows(page.runs ?? []); })
      .catch((caught) => {
        if (!live) return;
        setError(caught instanceof Error ? caught.message : 'The runs could not be loaded.');
        setRows([]);
        if (caught instanceof ApiError && caught.status === 401) toast({ title: 'Sign in again to use this.', variant: 'danger' });
      });
    return () => { live = false; };
  }, [toast]);

  return (
    <div className="view-enter space-y-6">
      <PageHeader eyebrow="Discovery package" title="Runs" description="Each run is one discovery file turned into costs, findings and a package to review." />
      {error ? <Notice tone="danger" title="The runs could not be loaded">{error}</Notice> : null}
      <Card className="overflow-x-auto p-0">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-[var(--color-gray-100)] text-[var(--color-gray-500)]">
              {['Run', 'Label', 'State', ''].map((heading) => <th key={heading || 'open'} className="px-4 py-3 font-medium">{heading}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows === null
              ? Array.from({ length: SKELETON_ROWS }, (_, index) => (
                  <tr key={index} className="border-b border-[var(--color-gray-100)]"><td className="px-4 py-3" colSpan={4}><Skeleton className="h-4 w-full" /></td></tr>
                ))
              : rows.map((row) => (
                  <tr key={row.run_id} className="border-b border-[var(--color-gray-100)]">
                    <td className="px-4 py-3">{row.run_id}</td>
                    <td className="px-4 py-3">{row.label || row.files?.[0] || ''}</td>
                    <td className="px-4 py-3">{row.finalised ? 'Final' : 'Draft'}</td>
                    <td className="px-4 py-3"><Button size="sm" variant="secondary" onClick={() => navigate('run', { id: row.run_id, stage: 'overview' })}>Open</Button></td>
                  </tr>
                ))}
          </tbody>
        </table>
        {rows?.length === 0 && !error ? <p className="px-4 py-6 text-sm text-[var(--color-gray-500)]">No runs yet. Start one from New run.</p> : null}
      </Card>
    </div>
  );
}

export function NewRunScreen({ navigate }: { navigate: Navigate }) {
  const toast = useToast();
  const actor = useActor();
  const [busy, setBusy] = useState(false);
  const [estate, setEstate] = useState<File[]>([]);
  const [licensing, setLicensing] = useState<File | null>(null);
  const [notes, setNotes] = useState<File[]>([]);
  const [label, setLabel] = useState('');
  const [days, setDays] = useState('');
  const [customer, setCustomer] = useState('');

  const submit = async () => {
    if (!estate.length) return;
    if (!actor.name) {
      toast({ title: 'Enter your name so this run is recorded against you.', variant: 'warning' });
      return;
    }
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        files: await Promise.all(estate.map(fileToB64)),
        label,
        collection_days: Number(days) || null,
        customer,
        by: actor.name,
      };
      if (licensing) body.licensing = await fileToB64(licensing);
      if (notes.length) body.notes = await Promise.all(notes.map(fileToB64));
      const created = await cvaRequest<{ run_id: string }>('/runs', body);
      toast({ title: 'Run created.', variant: 'success' });
      navigate('run', { id: created.run_id, stage: 'overview' });
    } catch (caught) {
      toast({ title: caught instanceof Error ? caught.message : 'The run was not created.', variant: 'danger' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view-enter space-y-6">
      <PageHeader eyebrow="Discovery package" title="New run" description="Start with the estate export. A licensing sheet and interview notes are optional." />
      <NameField name={actor.name} setName={actor.setName} />
      <Card className="space-y-4 p-4">
        {busy ? (
          <div className="flex items-center gap-4" role="status">
            <PackageMark busy />
            <p className="text-sm">Reading the files and building the first package.</p>
          </div>
        ) : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm sm:col-span-2">Estate export<input className={`${controlClass} mt-1`} type="file" accept=".xlsx,.zip,.csv" multiple onChange={(event) => setEstate([...(event.target.files ?? [])])} /></label>
          <label className="text-sm">Licensing input<input className={`${controlClass} mt-1`} type="file" accept=".xlsx,.json,.csv" onChange={(event) => setLicensing(event.target.files?.[0] ?? null)} /></label>
          <label className="text-sm">Interview notes<input className={`${controlClass} mt-1`} type="file" accept=".txt,.md" multiple onChange={(event) => setNotes([...(event.target.files ?? [])])} /></label>
          <label className="text-sm">Label<input className={`${controlClass} mt-1`} value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Customer A, September data" /></label>
          <label className="text-sm">Collection span in days<input className={`${controlClass} mt-1`} type="number" min={1} value={days} onChange={(event) => setDays(event.target.value)} /></label>
          <label className="text-sm sm:col-span-2">Customer label on the deck<input className={`${controlClass} mt-1`} value={customer} onChange={(event) => setCustomer(event.target.value)} /></label>
        </div>
        <Button disabled={busy || estate.length === 0} onClick={() => void submit()}>{estate.length ? 'Create run' : 'Choose the estate file first'}</Button>
      </Card>
    </div>
  );
}
