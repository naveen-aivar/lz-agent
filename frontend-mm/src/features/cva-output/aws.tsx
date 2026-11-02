'use client';

import { useCallback, useEffect, useState } from 'react';

import { cvaRequest, fileToB64 } from '@/features/cva-output/api';
import { PackageMark } from '@/features/cva-output/package-mark';
import { money } from '@/features/cva-output/types';
import { controlClass } from '@/shared/components/form-controls';
import { Notice } from '@/shared/components/notice';
import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';
import { Modal } from '@/shared/design-system/ui/modal';
import { Skeleton } from '@/shared/design-system/ui/skeleton';

interface TransformView {
  imported: boolean;
  assessment?: { scenario?: string; models?: { label: string; total: number; recommended?: boolean }[]; servers?: { total?: number; in_scope?: number }; warning_rows?: number } | null;
  environment: { mcp_installed: boolean; uvx?: boolean; aws_profile?: string; server_command?: string };
  job: { status: string; message?: string; events?: string[] };
  pending?: { kind?: string; reason?: string; tasks?: { taskId: string; title: string; category?: string; severity?: string; description?: string }[]; proposal?: string; reply?: string; question?: boolean; needs_listing?: boolean; workspaceId?: string; jobId?: string } | null;
  conversation?: { who: string; text: string }[];
  listed_input?: boolean;
  warnings?: { code: string; detail: { count?: number; impact?: string; recommendation?: string } }[];
}

export function AwsStage({ id, actor, canAct, onAct }: { id: string; actor: string; canAct: boolean; onAct: (path: string, body: unknown, ok: string) => Promise<void> }) {
  const [view, setView] = useState<TransformView | null>(null);
  const [error, setError] = useState('');
  const [checks, setChecks] = useState<{ ok: boolean; name: string; detail: string }[] | null>(null);
  const [approveFirst, setApproveFirst] = useState(true);
  const [enrich, setEnrich] = useState(false);
  const [allowUnlisted, setAllowUnlisted] = useState(false);
  const [suggest, setSuggest] = useState('');
  const [confirmStart, setConfirmStart] = useState(false);
  const [files, setFiles] = useState<File[]>([]);

  const load = useCallback(() => {
    cvaRequest<TransformView>(`/run/${id}/transform`).then(setView).catch((caught) => setError(caught instanceof Error ? caught.message : 'Could not load this.'));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (view?.job.status !== 'running') return;
    const timer = window.setInterval(() => { load(); }, 3000);
    return () => window.clearInterval(timer);
  }, [view?.job.status, load]);

  if (error) return <Notice tone="danger" title="AWS Transform could not be loaded">{error}</Notice>;
  if (!view) return <Skeleton className="h-40 w-full" />;
  const running = view.job.status === 'running';
  const pending = view.pending;

  return (
    <div className="view-enter space-y-4 text-sm">
      <p className="text-[var(--color-gray-500)]">The assessment service does the sizing and the pricing. This page prepares the input, runs the job, and brings the result back.</p>
      {running ? (
        <div className="flex items-center gap-4" role="status">
          <PackageMark busy />
          <p>An assessment is in progress. This page updates by itself. A run takes several minutes.</p>
        </div>
      ) : null}
      {view.imported ? <Notice tone="success" title={`Figures come from “${view.assessment?.scenario || 'the imported assessment'}”.`} /> : <Notice tone="warning" title="No assessment imported yet, so there are no cost figures from the service." />}
      {running ? (
        <Button size="sm" variant="secondary" disabled={!canAct} onClick={() => void onAct('/transform_cancel', {}, 'Stopped waiting. The job in the service keeps running.')}>Stop waiting</Button>
      ) : null}
      {(view.job.events ?? []).length ? <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-[var(--radius-md)] bg-[var(--color-gray-50)] p-3 text-xs">{view.job.events?.join('\n')}</pre> : null}
      {pending && !running ? <PendingPanel pending={pending} canAct={canAct} suggest={suggest} setSuggest={setSuggest} onAct={(path, body, ok) => onAct(path, body, ok)} /> : null}
      <Card className="space-y-3 p-4">
        <h3 className="font-semibold">Run the assessment</h3>
        {!view.environment.mcp_installed ? <Notice tone="danger" title="The connection tool is not installed where the service runs." /> : null}
        <label className="flex items-center gap-2"><input type="checkbox" checked={approveFirst} onChange={(event) => setApproveFirst(event.target.checked)} />Ask me to approve before it runs</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={enrich} onChange={(event) => setEnrich(event.target.checked)} />Second pass with our measurements</label>
        {view.listed_input ? null : <label className="flex items-center gap-2"><input type="checkbox" checked={allowUnlisted} onChange={(event) => setAllowUnlisted(event.target.checked)} />Try this file type anyway</label>}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => void cvaRequest<{ ok: boolean; checks: { ok: boolean; name: string; detail: string }[] }>('/transform_preflight', {}).then((result) => setChecks(result.checks)).catch((caught) => setError(caught instanceof Error ? caught.message : 'The check failed.'))}>Check the connection first</Button>
          <Button size="sm" disabled={!canAct || !view.environment.mcp_installed || running} onClick={() => setConfirmStart(true)}>{!canAct ? 'Enter your name first' : running ? 'Assessment in progress' : !view.environment.mcp_installed ? 'Connection is not ready' : 'Run the assessment'}</Button>
        </div>
        {checks ? <ul className="space-y-1">{checks.map((check) => <li key={check.name}>{check.ok ? 'Pass' : 'Fail'}: {check.name}. {check.detail}</li>)}</ul> : null}
      </Card>
      {view.assessment?.models ? (
        <Card className="p-4">
          <h3 className="mb-2 font-semibold">Pricing models</h3>
          <ul className="space-y-1">{view.assessment.models.map((model) => <li key={model.label}>{model.label}: {money(model.total)}{model.recommended ? ' · recommended' : ''}</li>)}</ul>
        </Card>
      ) : null}
      <div className="flex flex-wrap items-end gap-2">
        <Button size="sm" disabled={!canAct} onClick={() => void onAct('/transform_fetch_results', {}, 'Results fetched. The other steps are filled.')}>{canAct ? 'Fetch the results now' : 'Enter your name first'}</Button>
        <input type="file" multiple accept=".zip,.json,.csv,.xlsx" aria-label="Finished assessment" onChange={(event) => setFiles([...(event.target.files ?? [])])} />
        <Button size="sm" variant="secondary" disabled={!files.length} onClick={() => void Promise.all(files.map(fileToB64)).then((encoded) => onAct('/import_results', { files: encoded }, 'Assessment imported.'))}>Import file(s)</Button>
      </div>
      <Modal open={confirmStart} onOpenChange={setConfirmStart} title="Run this assessment?" description="This creates a job in the cloud account. It can take several minutes." footer={
        <>
          <Button variant="secondary" onClick={() => setConfirmStart(false)}>Not now</Button>
          <Button onClick={() => { setConfirmStart(false); void onAct('/transform_start', { enrich, allow_unlisted: allowUnlisted, require_approval: approveFirst }, 'Assessment started.'); }}>Run it</Button>
        </>
      } />
      <p className="sr-only">{actor}</p>
    </div>
  );
}

function PendingPanel({ pending, canAct, suggest, setSuggest, onAct }: { pending: NonNullable<TransformView['pending']>; canAct: boolean; suggest: string; setSuggest: (value: string) => void; onAct: (path: string, body: unknown, ok: string) => Promise<void> }) {
  return (
    <Card className="space-y-3 p-4">
      <Notice tone="warning" title={pending.reason || 'The service is waiting for a person.'} />
      {(pending.tasks ?? []).map((task) => (
        <div key={task.taskId} className="space-y-2">
          <p className="font-semibold">{task.title}</p>
          {task.description ? <pre className="whitespace-pre-wrap text-xs">{task.description}</pre> : null}
          <div className="flex gap-2">
            <Button size="sm" disabled={!canAct} onClick={() => void onAct('/transform_task', { taskId: task.taskId, decision: 'approve' }, 'Approval sent.')}>Approve</Button>
            <Button size="sm" variant="secondary" disabled={!canAct} onClick={() => void onAct('/transform_task', { taskId: task.taskId, decision: 'reject' }, 'Rejection sent.')}>Reject</Button>
          </div>
        </div>
      ))}
      {pending.proposal ? <pre className="whitespace-pre-wrap text-xs">{pending.proposal}</pre> : null}
      {pending.reply ? <pre className="whitespace-pre-wrap text-xs">{pending.reply}</pre> : null}
      <label className="block">Suggest a change<textarea className={`${controlClass} mt-1`} rows={3} value={suggest} onChange={(event) => setSuggest(event.target.value)} /></label>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" disabled={!canAct || !suggest.trim()} onClick={() => void onAct('/transform_suggest', { text: suggest }, 'Sent. Waiting for the answer.')}>{suggest.trim() ? 'Send suggestion' : 'Type a suggestion first'}</Button>
        {pending.needs_listing ? <Button size="sm" disabled={!canAct} onClick={() => void onAct('/transform_listing', {}, 'Asking for the exact configuration.')}>Show what it will run</Button> : null}
        <Button size="sm" variant="secondary" disabled={!canAct} onClick={() => void onAct('/transform_resume', {}, 'Checking again.')}>Check again</Button>
        <Button size="sm" disabled={!canAct} onClick={() => void onAct('/transform_resume', { approve: true }, 'Approved. Sending the go-ahead.')}>Approve and run</Button>
      </div>
    </Card>
  );
}
