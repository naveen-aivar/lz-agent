'use client';

import { useCallback, useEffect, useState } from 'react';
import { orchestratorApi, type Handover } from '@/features/orchestrator/api';
import { messageOf } from '@/features/orchestrator/run-list';
import { DECKS, EMPTY_TRIGGER, planRun, SOURCES, type TriggerForm } from '@/features/orchestrator/trigger';
import { formatBytes, formatDate } from '@/features/tco/format';
import type { Navigate } from '@/features/agents/types';
import { PageHeader } from '@/shared/components/page-header';
import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';
import { useToast } from '@/shared/design-system/ui/toaster';

const INPUT = 'mt-1 w-full rounded-[var(--radius-md)] border border-[var(--color-gray-200)] px-3 py-2 text-sm';

/** What a person sees for one choice: the job id first, then when it came and what it holds. */
export function optionText(handover: Handover, source: string): string {
  const files = handover.sources[source]?.files ?? [];
  const what = files.map((file) => `${file.filename} (${formatBytes(file.size)})`).join(', ');
  return [handover.job_id, formatDate(handover.created_at), handover.customer, what].filter(Boolean).join(' · ');
}

/** The trigger: choose the decks and the job each source is taken from, then start. Nothing is uploaded here. */
export function GenerateDecks({ navigate }: { navigate: Navigate }) {
  const toast = useToast();
  const [form, setForm] = useState<TriggerForm>(EMPTY_TRIGGER);
  const [handovers, setHandovers] = useState<Handover[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    setLoadError('');
    setHandovers(null);
    void orchestratorApi
      .handovers()
      .then((result) => setHandovers(result.handovers))
      .catch((caught: unknown) => {
        setLoadError(messageOf(caught));
        setHandovers([]);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggleDeck = (id: string, on: boolean) =>
    setForm((current) => ({ ...current, decks: on ? [...current.decks, id] : current.decks.filter((deck) => deck !== id) }));

  const preview = planRun(form);
  const missing = 'plan' in preview ? preview.plan.missingSources : [];

  const submit = () => {
    setError('');
    const result = planRun(form);
    if ('error' in result) return setError(result.error);
    setBusy(true);
    void (async () => {
      try {
        const created = await orchestratorApi.createRun(result.plan.request);
        await orchestratorApi.startRun(created.job_id);
        toast({ title: 'Building the decks.', variant: 'success' });
        navigate('run', { id: created.job_id });
      } catch (caught) {
        setError(messageOf(caught));
        toast({ title: 'The decks could not be started.', description: messageOf(caught), variant: 'danger' });
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <div className="view-enter">
      <PageHeader title="Generate decks" description="Choose the job each assessment agent handed its files over under. The service reads the files itself. It takes about 5 to 10 minutes." />
      <Card className="mt-4 p-5">
        <form
          className="grid gap-5"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <fieldset className="grid gap-2">
            <legend className="text-sm font-medium">Decks</legend>
            {DECKS.map((deck) => (
              <label key={deck.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.decks.includes(deck.id)} onChange={(event) => toggleDeck(deck.id, event.target.checked)} />
                {deck.label}
                <span className="text-[var(--color-gray-500)]">uses {deck.sources.map((id) => SOURCES.find((source) => source.id === id)?.label).join(', ')}</span>
              </label>
            ))}
          </fieldset>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="orch-customer" className="text-sm font-medium">Customer <span className="text-[var(--color-gray-500)]">(optional with an MRA job)</span></label>
              <input id="orch-customer" className={INPUT} maxLength={80} value={form.customer} onChange={(event) => setForm((current) => ({ ...current, customer: event.target.value }))} />
            </div>
            <div>
              <label htmlFor="orch-date" className="text-sm font-medium">Date <span className="text-[var(--color-gray-500)]">(optional, today by default)</span></label>
              <input id="orch-date" className={INPUT} type="date" value={form.date} onChange={(event) => setForm((current) => ({ ...current, date: event.target.value }))} />
            </div>
          </div>
          <div className="grid gap-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">Jobs to build from</p>
              <Button type="button" variant="secondary" size="sm" onClick={load} disabled={handovers === null}>Refresh</Button>
            </div>
            {loadError ? <p className="text-sm text-[var(--color-danger-700)]" role="alert">The jobs could not be loaded. {loadError}</p> : null}
            {SOURCES.map((source) => {
              const options = (handovers ?? []).filter((handover) => handover.sources[source.id]);
              return (
                <div key={source.id}>
                  <label htmlFor={`orch-${source.id}`} className="text-sm">{source.label} <span className="text-[var(--color-gray-500)]">{source.hint}</span></label>
                  <select
                    id={`orch-${source.id}`}
                    className={INPUT}
                    value={form.picked[source.id] ?? ''}
                    disabled={handovers === null}
                    onChange={(event) => setForm((current) => ({ ...current, picked: { ...current.picked, [source.id]: event.target.value } }))}
                  >
                    <option value="">{handovers === null ? 'Loading…' : options.length ? 'Not included' : 'No jobs yet'}</option>
                    {options.map((handover) => (
                      <option key={handover.job_id} value={handover.job_id} disabled={!handover.sources[source.id]?.complete}>
                        {optionText(handover, source.id)}{handover.sources[source.id]?.complete ? '' : ' (incomplete)'}
                      </option>
                    ))}
                  </select>
                </div>
              );
            })}
          </div>
          {missing.length ? (
            <p className="text-sm text-[var(--color-warning-700)]" role="status">
              No job for {missing.join(', ')}. Those slides will say the data is not available.
            </p>
          ) : null}
          {error ? <p className="text-sm text-[var(--color-danger-700)]" role="alert">{error}</p> : null}
          <div><Button type="submit" loading={busy}>Generate decks</Button></div>
        </form>
      </Card>
    </div>
  );
}
