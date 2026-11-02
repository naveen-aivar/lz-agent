'use client';

import { useEffect, useState } from 'react';

import { cvaRequest } from '@/features/cva-output/api';
import { money, type CvaOverview } from '@/features/cva-output/types';
import { controlClass } from '@/shared/components/form-controls';
import { Notice } from '@/shared/components/notice';
import { Badge } from '@/shared/design-system/ui/badge';
import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';
import { Modal } from '@/shared/design-system/ui/modal';
import { Skeleton } from '@/shared/design-system/ui/skeleton';

function countLabel(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function priceState(status: string): string {
  if (status === 'not_computable') return 'Cannot be priced yet';
  if (status === 'partial') return 'Partly priced';
  return status.replace(/_/g, ' ');
}

function useLoad<T>(path: string): { data: T | null; error: string } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    cvaRequest<T>(path).then((value) => { if (live) setData(value); }).catch((caught) => { if (live) setError(caught instanceof Error ? caught.message : 'Could not load this.'); });
    return () => { live = false; };
  }, [path]);
  return { data, error };
}

export function OverviewStage({ overview, onEstimate, onAws }: { overview: CvaOverview; onEstimate: () => void; onAws: () => void }) {
  const max = Math.max(...overview.scenarios.map((scenario) => scenario.total || 0), 1);
  return (
    <div className="view-enter space-y-4">
      <p className="text-sm">{overview.commentary?.executive_summary?.text}</p>
      {overview.meta.figures_source === 'aws_transform' ? <Notice tone="success" title="These figures come from the imported assessment." /> : null}
      {overview.meta.figures_source === 'a01_estimate' ? <Notice tone="warning" title="These figures are an offline estimate, not the cloud price list."><p>Import an assessment on AWS Transform for the numbers from the service.</p></Notice> : null}
      {!overview.scenarios.length ? (
        <Card className="space-y-2 p-4">
          <h3 className="text-sm font-semibold">No cost figures yet</h3>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={onAws}>Go to AWS Transform</Button>
            {overview.estimate_ran ? null : <Button size="sm" variant="secondary" onClick={onEstimate}>Run the offline estimate</Button>}
          </div>
        </Card>
      ) : null}
      <div className="space-y-2" role="list">
        {overview.scenarios.map((scenario) => (
          <div key={scenario.id} className="grid items-center gap-2 sm:grid-cols-[9rem_1fr_8rem]" role="listitem">
            <span className="text-sm">{scenario.label}</span>
            <span className="block h-2 overflow-hidden rounded-full bg-[var(--color-gray-100)]">
              <span className="cva-bar-fill block h-full bg-[var(--color-primary-600)]" style={{ width: scenario.total == null ? '3%' : `${Math.max(3, (100 * scenario.total) / max)}%`, opacity: scenario.status === 'computed' ? 1 : 0.45 }} />
            </span>
            <span className="text-sm">{scenario.total == null ? priceState(scenario.status) : money(scenario.total)}</span>
          </div>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Card className="p-4 text-sm"><p className="font-semibold">Licensing</p><p>{overview.licensing?.mode}</p></Card>
        <Card className="p-4 text-sm"><p className="font-semibold">How complete the data is</p><p>Grade {overview.meta.richness?.grade}. {overview.meta.richness?.label}</p></Card>
        <Card className="p-4 text-sm"><p className="font-semibold">Review</p><p>{countLabel(overview.kpis?.proposals?.pending ?? 0, 'proposal', 'proposals')} waiting. {countLabel(overview.gate?.open ?? 0, 'review item', 'review items')} open.</p></Card>
      </div>
    </div>
  );
}

export function WorkloadsStage({ id }: { id: string }) {
  const { data, error } = useLoad<Array<Record<string, unknown>>>(`/run/${id}/workloads`);
  const [query, setQuery] = useState('');
  if (error) return <Notice tone="danger" title="Workloads could not be loaded">{error}</Notice>;
  if (!data) return <Skeleton className="h-40 w-full" />;
  const rows = data.filter((row) => String(row.name || '').toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="view-enter space-y-3">
      <p className="text-sm text-[var(--color-gray-500)]">One row per server. Open a row for sizing, cost, licensing and lifecycle.</p>
      <input className={`${controlClass} max-w-sm`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by name" aria-label="Search workloads" />
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead><tr className="text-[var(--color-gray-500)]">{['Name', 'OS', 'Direction', 'Confidence'].map((heading) => <th key={heading} className="py-2 pr-3 font-medium">{heading}</th>)}</tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.name)} className="border-t border-[var(--color-gray-100)]">
                <td className="py-2 pr-3">
                  <details>
                    <summary>{String(row.name || '')}</summary>
                    <WorkloadDetail id={id} name={String(row.name || '')} />
                  </details>
                </td>
                <td className="py-2 pr-3">{String(row.os || '')}</td>
                <td className="py-2 pr-3">{String(row.direction || '')}</td>
                <td className="py-2">{String(row.confidence || '')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function WorkloadDetail({ id, name }: { id: string; name: string }) {
  const { data } = useLoad<{ workload?: Record<string, unknown>; sizing?: { notes?: string[] }; lifecycle?: { label: string; status: string; end_of_support: string }[]; exceptions?: { code: string; severity: string; message: string }[] }>(`/run/${id}/workload?name=${encodeURIComponent(name)}`);
  if (!data) return <Skeleton className="mt-2 h-16 w-full" />;
  return (
    <div className="mt-2 space-y-1 text-sm text-[var(--color-gray-700)]">
      {(data.lifecycle ?? []).map((item) => <p key={item.label}>{item.label}: {item.status.replace(/_/g, ' ')} ({item.end_of_support})</p>)}
      {(data.exceptions ?? []).map((item) => <p key={item.code}><Badge variant={item.severity === 'error' ? 'danger' : 'warning'}>{item.code}</Badge> {item.message}</p>)}
      {(data.sizing?.notes ?? []).map((note) => <p key={note}>{note}</p>)}
    </div>
  );
}

export function LicensingStage({ id }: { id: string }) {
  const { data, error } = useLoad<{ mode: string; provenance: string; coverage: { sql_pct: number | null; windows_pct: number | null }; scenario?: { status: string; notes: string[] }; findings: Record<string, string>[]; gaps: Record<string, string>[] }>(`/run/${id}/licensing`);
  if (error) return <Notice tone="danger" title="Licensing could not be loaded">{error}</Notice>;
  if (!data) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="view-enter space-y-3 text-sm">
      <p>Input on this run: {data.mode} ({data.provenance}).</p>
      <p>SQL Server {data.coverage.sql_pct == null ? 'not detected' : `${data.coverage.sql_pct}%`}. Windows Server {data.coverage.windows_pct ?? 0}%.</p>
      {data.scenario ? <Notice tone={data.scenario.status === 'computed' ? 'success' : 'warning'} title={`BYOL scenario: ${data.scenario.status.replace(/_/g, ' ')}`}>{data.scenario.notes?.join(' ')}</Notice> : null}
      <h3 className="font-semibold">Findings ({data.findings.length})</h3>
      <SimpleTable headers={['Workload', 'Product', 'Model', 'Origin']} rows={data.findings.slice(0, 200).map((row) => [row.workload, row.product, row.model, row.origin])} />
      <h3 className="font-semibold">Gaps ({data.gaps.length})</h3>
      <SimpleTable headers={['Workload', 'Product', 'Reason']} rows={data.gaps.slice(0, 200).map((row) => [row.workload, row.product, row.reason])} />
    </div>
  );
}

export function ExceptionsStage({ id, canAct, onAck }: { id: string; canAct: boolean; onAck: (body: unknown, ok: string) => void }) {
  const { data, error } = useLoad<{ id: string; severity: string; code: string; workload?: string; message: string; acked?: boolean }[]>(`/run/${id}/issues`);
  const [severity, setSeverity] = useState('all');
  const [code, setCode] = useState('');
  const [note, setNote] = useState('');
  if (error) return <Notice tone="danger" title="Exceptions could not be loaded">{error}</Notice>;
  if (!data) return <Skeleton className="h-40 w-full" />;
  const codes = [...new Set(data.map((item) => item.code))].sort();
  const rows = data.filter((item) => severity === 'all' || item.severity === severity);
  return (
    <div className="view-enter space-y-3">
      <p className="text-sm text-[var(--color-gray-500)]">Acknowledging an exception is a recorded decision. It does not hide the finding.</p>
      <div className="grid gap-3 sm:grid-cols-[10rem_12rem_1fr_auto] sm:items-end">
        <label className="text-sm">Severity<select className={`${controlClass} mt-1`} value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="all">All</option><option value="error">error</option><option value="warn">warn</option><option value="info">info</option></select></label>
        <label className="text-sm">Code<select className={`${controlClass} mt-1`} value={code || codes[0] || ''} onChange={(event) => setCode(event.target.value)}>{codes.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="text-sm">Why this is acceptable<input className={`${controlClass} mt-1`} value={note} onChange={(event) => setNote(event.target.value)} /></label>
        <Button size="sm" disabled={!canAct || !note.trim() || !codes.length} onClick={() => onAck({ code: code || codes[0], note }, `Acknowledged ${code || codes[0]}.`)}>{note.trim() ? 'Acknowledge' : 'Add a note first'}</Button>
      </div>
      <SimpleTable headers={['ID', 'Severity', 'Code', 'Workload', 'Message', '']} rows={rows.slice(0, 400).map((item) => [item.id, item.severity, item.code, item.workload || '', item.message, item.acked ? 'acknowledged' : ''])} />
    </div>
  );
}

export function AgentStage({ id, busy, canAct, onRun, onDecide }: { id: string; busy: boolean; canAct: boolean; onRun: (task: string | null, mode: string) => void; onDecide: (body: unknown, ok: string) => void }) {
  const { data: proposals } = useLoad<Array<{ id: string; status: string; type: string; source: string; task: string; rationale: string; payload: { text?: string; note_id?: string; quote?: string } }>>(`/run/${id}/proposals`);
  const { data: transcripts } = useLoad<string[]>(`/run/${id}/transcripts`);
  const [mode, setMode] = useState('stub');
  const [open, setOpen] = useState('');
  return (
    <div className="view-enter space-y-3 text-sm">
      <p className="text-[var(--color-gray-500)]">The assistant proposes. It cannot change a number or a decision until you accept.</p>
      <div className="flex flex-wrap items-end gap-2">
        <label>Model<select className={`${controlClass} mt-1`} value={mode} onChange={(event) => setMode(event.target.value)} aria-label="Model"><option value="stub">Offline plan</option><option value="bedrock">Cloud model</option></select></label>
        <Button size="sm" disabled={!canAct || busy} onClick={() => onRun(null, mode)}>{canAct ? 'Let it decide what this run needs' : 'Enter your name first'}</Button>
        {['licensing', 'parity', 'narrative', 'intake'].map((task) => <Button key={task} size="sm" variant="secondary" disabled={!canAct || busy} onClick={() => onRun(task, mode)}>Run {task}</Button>)}
      </div>
      {(proposals ?? []).map((proposal) => (
        <Card key={proposal.id} className="space-y-2 p-4">
          <div className="flex flex-wrap gap-2"><Badge>{proposal.id}</Badge><Badge variant={proposal.status === 'accepted' ? 'success' : proposal.status === 'pending' ? 'warning' : 'muted'}>{proposal.status}</Badge><Badge variant="muted">{proposal.type}</Badge></div>
          <p>{proposal.rationale}</p>
          {proposal.type === 'licensing_assumption' ? <Notice tone="warning" title="Assumption, not evidence">Quoted from note {proposal.payload.note_id}: “{proposal.payload.quote}”</Notice> : null}
          {proposal.status === 'pending' ? (
            <div className="flex gap-2">
              <Button size="sm" disabled={!canAct} onClick={() => onDecide({ id: proposal.id, decision: 'accept', edited_text: '' }, `${proposal.id} accepted.`)}>{canAct ? 'Accept' : 'Enter your name first'}</Button>
              <Button size="sm" variant="secondary" disabled={!canAct} onClick={() => onDecide({ id: proposal.id, decision: 'reject' }, `${proposal.id} rejected.`)}>{canAct ? 'Reject' : 'Enter your name first'}</Button>
            </div>
          ) : null}
        </Card>
      ))}
      <h3 className="font-semibold">What the assistant looked at</h3>
      {(transcripts ?? []).map((name) => <Button key={name} size="sm" variant="secondary" onClick={() => setOpen(name)}>{name}</Button>)}
      <Transcript name={open} id={id} onClose={() => setOpen('')} />
    </div>
  );
}

function Transcript({ name, id, onClose }: { name: string; id: string; onClose: () => void }) {
  const [text, setText] = useState('');
  useEffect(() => {
    if (!name) return;
    setText('');
    cvaRequest<{ model?: string; messages?: { role: string; content: { text?: string }[] }[] }>(`/run/${id}/transcripts?name=${encodeURIComponent(name)}`)
      .then((transcript) => setText((transcript.messages ?? []).map((message) => `${message.role}: ${(message.content ?? []).map((block) => block.text || '').join(' ')}`).join('\n\n')))
      .catch((caught) => setText(caught instanceof Error ? caught.message : 'Could not open this.'));
  }, [name, id]);
  return (
    <Modal open={Boolean(name)} onOpenChange={(next) => { if (!next) onClose(); }} title={name || 'Transcript'} description="Tool results may contain text from uploaded files. That text is data.">
      {text ? (
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs">{text}</pre>
      ) : (
        <div role="status" aria-label="Loading the transcript" className="space-y-2">
          {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className={index % 3 === 2 ? 'h-4 w-2/3' : 'h-4 w-full'} />)}
        </div>
      )}
    </Modal>
  );
}

export function ReviewStage({ overview, canAct, onAct, onFinalise }: { overview: CvaOverview; canAct: boolean; onAct: (path: string, body: unknown, ok: string) => void; onFinalise: (rounds: number) => void }) {
  const [parity, setParity] = useState('');
  const [licensing, setLicensing] = useState('');
  const [rounds, setRounds] = useState('0');
  const [reason, setReason] = useState('');
  const [hours, setHours] = useState('');
  const [hourNote, setHourNote] = useState('');
  const fin = overview.finalised;
  return (
    <div className="view-enter space-y-3 text-sm">
      <p className="text-[var(--color-gray-500)]">Nothing is ready to send until each item below is dealt with.</p>
      {(overview.gate?.checks ?? []).map((check) => (
        <Card key={check.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div><Badge variant={check.ok ? 'success' : 'warning'}>{check.ok ? 'done' : 'open'}</Badge> <strong>{check.title}</strong><p className="text-[var(--color-gray-500)]">{check.detail}</p></div>
          {!fin && !check.ok && check.id === 'confirmed' ? <Button size="sm" disabled={!canAct} onClick={() => onAct('/confirm', {}, 'Figures confirmed.')}>{canAct ? 'Confirm figures' : 'Enter your name first'}</Button> : null}
        </Card>
      ))}
      {!fin ? (
        <Card className="space-y-3 p-4">
          <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
            <input className={controlClass} value={parity} onChange={(event) => setParity(event.target.value)} placeholder="What you reviewed" aria-label="Parity note" />
            <Button size="sm" variant="secondary" disabled={!canAct} onClick={() => onAct('/ack_parity', { note: parity }, 'Review recorded.')}>{canAct ? 'Mark reviewed' : 'Enter your name first'}</Button>
            <input className={controlClass} value={licensing} onChange={(event) => setLicensing(event.target.value)} placeholder="Licensing position accepted for this release" aria-label="Licensing note" />
            <Button size="sm" variant="secondary" disabled={!canAct} onClick={() => onAct('/ack_licensing', { note: licensing }, 'Licensing position recorded.')}>{canAct ? 'Licensing acknowledged' : 'Enter your name first'}</Button>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-sm">Rework rounds<input className={`${controlClass} mt-1 w-24`} type="number" min={0} value={rounds} onChange={(event) => setRounds(event.target.value)} /></label>
            <Button size="sm" disabled={!canAct || !overview.gate?.ready} onClick={() => onFinalise(Number(rounds) || 0)}>{!canAct ? 'Enter your name first' : overview.gate?.ready ? 'Finalise and lock' : 'Not ready to finalise'}</Button>
          </div>
        </Card>
      ) : (
        <div className="flex flex-wrap items-end gap-2">
          <Notice tone="success" title={`Finalised by ${fin.by}. The run is locked.`} />
          <input className={`${controlClass} max-w-sm`} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Reason for reopening" aria-label="Reason" />
          <Button size="sm" variant="secondary" disabled={!canAct || !reason.trim()} onClick={() => onAct('/reopen', { reason }, 'Reopened.')}>{reason.trim() ? 'Reopen' : 'Add a reason first'}</Button>
        </div>
      )}
      <div className="grid items-end gap-3 sm:grid-cols-[8rem_minmax(0,1fr)_auto]">
        <label className="text-sm">Hours<input className={`${controlClass} mt-1`} type="number" min={0} step="0.25" value={hours} onChange={(event) => setHours(event.target.value)} aria-label="Hours" /></label>
        <label className="text-sm">What the time was spent on<input className={`${controlClass} mt-1`} value={hourNote} onChange={(event) => setHourNote(event.target.value)} aria-label="Hours note" /></label>
        <Button size="sm" variant="secondary" disabled={!canAct || Boolean(fin)} onClick={() => onAct('/hours', { hours: Number(hours) || 0, note: hourNote }, 'Hours logged.')}>{canAct ? 'Log hours' : 'Enter your name first'}</Button>
      </div>
    </div>
  );
}

export function OutputsStage({ id, canAct, onExport }: { id: string; canAct: boolean; onExport: (template: string) => void }) {
  const { data, error } = useLoad<{ files: string[] }>(`/run/${id}/outputs`);
  const [template, setTemplate] = useState('');
  if (error) return <Notice tone="danger" title="Outputs could not be loaded">{error}</Notice>;
  return (
    <div className="view-enter space-y-3 text-sm">
      <p className="text-[var(--color-gray-500)]">The deck, the workbook that traces every figure, and the exceptions list. Until the run is finalised every file is marked draft.</p>
      <div className="flex flex-wrap items-end gap-2">
        <input className={`${controlClass} max-w-md`} value={template} onChange={(event) => setTemplate(event.target.value)} placeholder="Path to the approved deck template, optional" aria-label="Template path" />
        <Button size="sm" disabled={!canAct} onClick={() => onExport(template)}>{canAct ? 'Build deck and workbook' : 'Enter your name first'}</Button>
      </div>
      <h3 className="font-semibold">Files in this run</h3>
      {(data?.files ?? []).length === 0 ? <p className="text-[var(--color-gray-500)]">None yet.</p> : null}
      <ul className="list-disc pl-4">{(data?.files ?? []).map((name) => <li key={name}>{name}</li>)}</ul>
    </div>
  );
}

export function AuditStage({ id }: { id: string }) {
  const { data, error } = useLoad<{ verify: { ok: boolean; message: string; entries: number }; entries: { n: number; ts: string; event: string; actor: string; data: unknown }[] }>(`/run/${id}/audit`);
  if (error) return <Notice tone="danger" title="The audit could not be loaded">{error}</Notice>;
  if (!data) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="view-enter space-y-3 text-sm">
      <Notice tone={data.verify.ok ? 'success' : 'danger'} title={data.verify.message}>{data.verify.entries} entries.</Notice>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead><tr className="text-[var(--color-gray-500)]">{['#', 'Time', 'Event', 'Actor', 'Data'].map((heading) => <th key={heading} className="py-2 pr-3 font-medium">{heading}</th>)}</tr></thead>
          <tbody>
            {[...data.entries].reverse().map((entry) => (
              <tr key={entry.n} className="border-t border-[var(--color-gray-100)]">
                <td className="py-2 pr-3">{entry.n}</td>
                <td className="py-2 pr-3">{entry.ts}</td>
                <td className="py-2 pr-3">{entry.event}</td>
                <td className="py-2 pr-3">{entry.actor}</td>
                <td className="py-2">{JSON.stringify(entry.data).slice(0, 160)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SimpleTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead><tr className="text-[var(--color-gray-500)]">{headers.map((heading) => <th key={heading || 'end'} className="py-2 pr-3 font-medium">{heading}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={index} className="border-t border-[var(--color-gray-100)]">{row.map((cell, cellIndex) => <td key={cellIndex} className="py-2 pr-3">{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}
