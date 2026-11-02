'use client';

import { useEffect, useState } from 'react';

import { ApiError, mraRequest, uploadFile } from '@/features/mra/api';
import { NameField, useActor } from '@/features/mra/actor';
import { ReadinessMark } from '@/features/mra/readiness';
import type { MraInfo, MraRunRow } from '@/features/mra/types';
import type { Navigate } from '@/features/agents/types';
import { controlClass } from '@/shared/components/form-controls';
import { Notice } from '@/shared/components/notice';
import { PageHeader } from '@/shared/components/page-header';
import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';
import { Skeleton } from '@/shared/design-system/ui/skeleton';
import { useToast } from '@/shared/design-system/ui/toaster';

const SKELETON_ROWS = 15;

const DETAILS = [
  { key: 'facilitator', label: 'Facilitator', type: 'text' },
  { key: 'presenter', label: 'Presenter', type: 'text' },
  { key: 'workshop_date', label: 'Workshop date', type: 'date' },
  { key: 'readout_date', label: 'Readout date', type: 'date' },
  { key: 'internal_contact', label: 'Internal contact', type: 'text' },
  { key: 'sponsor_contact', label: 'Sponsor contact', type: 'text' },
] as const;

function textOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.';
}

export function RunsScreen({ navigate }: { navigate: Navigate }) {
  const toast = useToast();
  const [rows, setRows] = useState<MraRunRow[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    mraRequest<{ runs: MraRunRow[] }>('GET', '/runs')
      .then((page) => {
        if (live) setRows(page.runs ?? []);
      })
      .catch((caught) => {
        if (!live) return;
        setError(textOf(caught));
        setRows([]);
        if (caught instanceof ApiError && caught.status === 401) toast({ title: 'Sign in again to use this.', variant: 'danger' });
      });
    return () => {
      live = false;
    };
  }, [toast]);

  return (
    <div className="view-enter space-y-6">
      <PageHeader eyebrow="Readiness" title="Runs" description="Each run is one questionnaire, scored and ready to review." />
      {error ? <Notice tone="danger" title="The runs could not be loaded">{error}</Notice> : null}
      <Card className="overflow-x-auto p-0">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-[var(--color-gray-100)] text-[var(--color-gray-500)]">
              {['Customer', 'Run', 'State', 'Blank ratings', 'Opened'].map((heading) => (
                <th key={heading} className="px-4 py-3 font-medium">{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows === null
              ? Array.from({ length: SKELETON_ROWS }, (_, index) => (
                  <tr key={index} className="border-b border-[var(--color-gray-100)]">
                    <td className="px-4 py-3" colSpan={5}><Skeleton className="h-4 w-full" /></td>
                  </tr>
                ))
              : rows.map((row) => (
                  <tr key={row.set_id} className="border-b border-[var(--color-gray-100)]">
                    <td className="px-4 py-3">{row.customer}</td>
                    <td className="px-4 py-3">{row.set_id}</td>
                    <td className="px-4 py-3">{row.final ? 'Final' : 'Draft'}</td>
                    <td className="px-4 py-3">{row.blank_ratings || 'none'}</td>
                    <td className="px-4 py-3">
                      <span className="mr-3 text-[var(--color-gray-500)]">{(row.generated_at || '').replace('T', ' ').replace(/\+00:00$/, ' UTC')}</span>
                      <Button size="sm" variant="secondary" onClick={() => navigate('run', { id: row.set_id, stage: 'overview' })}>Open</Button>
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
        {rows?.length === 0 && !error ? <p className="px-4 py-6 text-sm text-[var(--color-gray-500)]">No runs yet. Start one from New assessment.</p> : null}
      </Card>
    </div>
  );
}

export function NewRunScreen({ navigate }: { navigate: Navigate }) {
  const toast = useToast();
  const actor = useActor();
  const [info, setInfo] = useState<MraInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [customer, setCustomer] = useState('');
  const [runId, setRunId] = useState('');
  const [details, setDetails] = useState<Record<string, string>>({});
  const [file, setFile] = useState<File | null>(null);
  const [notes, setNotes] = useState<File[]>([]);

  useEffect(() => {
    mraRequest<MraInfo>('GET', '/info').then(setInfo).catch(() => setInfo(null));
  }, []);

  const missingFile = !file;
  const submit = async () => {
    if (!file) return;
    if (!actor.name) {
      toast({ title: 'Enter your name so this run is recorded against you.', variant: 'warning' });
      return;
    }
    setBusy(true);
    try {
      const uploadedNotes = [];
      for (const note of notes) uploadedNotes.push({ name: note.name, upload_id: await uploadFile(note, 'note') });
      const created = await mraRequest<{ set_id: string }>('POST', '/runs', {
        file_name: file.name,
        upload_id: await uploadFile(file, 'questionnaire'),
        set_id: runId.trim(),
        customer: customer.trim(),
        notes: uploadedNotes,
        meta: Object.fromEntries(Object.entries(details).filter(([, value]) => value.trim())),
      });
      toast({ title: 'Scored. Check the blank ratings, then work through the review.', variant: 'success' });
      navigate('run', { id: created.set_id, stage: 'overview' });
    } catch (caught) {
      toast({ title: textOf(caught), variant: 'danger' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view-enter space-y-6">
      <PageHeader eyebrow="Readiness" title="New assessment" description="Upload the filled-in questionnaire. Interview notes are optional." />
      <NameField name={actor.name} setName={actor.setName} />
      <Card className="space-y-4 p-4">
        {busy ? (
          <div className="flex items-center gap-4" role="status">
            <ReadinessMark done={0} total={1} busy />
            <p className="text-sm text-[var(--color-gray-700)]">Reading and scoring the questionnaire. This can take a minute.</p>
          </div>
        ) : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm sm:col-span-2">
            Filled-in questionnaire
            <input className={`${controlClass} mt-1`} type="file" accept=".xlsx,.xlsm,.csv,.tsv" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </label>
          <label className="text-sm sm:col-span-2">
            Interview notes
            <input className={`${controlClass} mt-1`} type="file" accept=".txt,.md" multiple onChange={(event) => setNotes([...(event.target.files ?? [])])} />
          </label>
          <label className="text-sm">Customer name<input className={`${controlClass} mt-1`} value={customer} onChange={(event) => setCustomer(event.target.value)} placeholder="Taken from the file name if empty" /></label>
          <label className="text-sm">Run id<input className={`${controlClass} mt-1`} value={runId} onChange={(event) => setRunId(event.target.value)} placeholder="Taken from the file name if empty" /></label>
          {DETAILS.map((field) => (
            <label key={field.key} className="text-sm">
              {field.label}
              <input className={`${controlClass} mt-1`} type={field.type} value={details[field.key] ?? ''} onChange={(event) => setDetails((current) => ({ ...current, [field.key]: event.target.value }))} />
            </label>
          ))}
        </div>
        {info?.user && info.user.can_write === false ? <p className="text-sm text-[var(--color-gray-500)]">This account can read but not start a run.</p> : null}
        <Button disabled={busy || missingFile || info?.user?.can_write === false} onClick={() => void submit()}>
          {missingFile ? 'Choose the questionnaire first' : 'Score it'}
        </Button>
      </Card>
    </div>
  );
}
