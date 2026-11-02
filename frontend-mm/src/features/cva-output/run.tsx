'use client';

import { useCallback, useEffect, useState } from 'react';

import { NameField, useActor } from '@/features/cva-output/actor';
import { cvaRequest } from '@/features/cva-output/api';
import { AwsStage } from '@/features/cva-output/aws';
import { AgentStage, AuditStage, ExceptionsStage, LicensingStage, OutputsStage, OverviewStage, ReviewStage, WorkloadsStage } from '@/features/cva-output/stages';
import { PackageStepper } from '@/features/cva-output/stepper';
import { CVA_STAGES, type CvaOverview, type CvaStage } from '@/features/cva-output/types';
import type { Navigate } from '@/features/agents/types';
import { Notice } from '@/shared/components/notice';
import { PageHeader } from '@/shared/components/page-header';
import { Badge } from '@/shared/design-system/ui/badge';
import { Button } from '@/shared/design-system/ui/button';
import { Modal } from '@/shared/design-system/ui/modal';
import { Skeleton, SkeletonText } from '@/shared/design-system/ui/skeleton';
import { useToast } from '@/shared/design-system/ui/toaster';

function isStage(value: string): value is CvaStage {
  return CVA_STAGES.some((item) => item.id === value);
}

export function RunScreen({ id, stage, navigate }: { id: string; stage: string; navigate: Navigate }) {
  const toast = useToast();
  const actor = useActor();
  const current = isStage(stage) ? stage : 'overview';
  const [overview, setOverview] = useState<CvaOverview | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmFinal, setConfirmFinal] = useState<number | null>(null);

  const load = useCallback(async () => {
    setOverview(await cvaRequest<CvaOverview>(`/run/${id}/overview`));
    setError('');
  }, [id]);

  useEffect(() => {
    setOverview(null);
    load().catch((caught) => setError(caught instanceof Error ? caught.message : 'The run could not be loaded.'));
  }, [load]);

  const act = async (path: string, extra: unknown, ok: string) => {
    if (!actor.name) {
      toast({ title: 'Enter your name so this decision is recorded against you.', variant: 'warning' });
      return;
    }
    setBusy(true);
    try {
      const body = { ...(typeof extra === 'object' && extra ? extra : {}), by: actor.name };
      await cvaRequest(`/run/${id}${path}`, body);
      await load();
      toast({ title: ok, variant: 'success' });
    } catch (caught) {
      toast({ title: caught instanceof Error ? caught.message : 'That did not work.', variant: 'danger' });
    } finally {
      setBusy(false);
    }
  };

  const gate = overview?.gate;
  return (
    <div className="space-y-4">
      <PageHeader
        eyebrow="Discovery package"
        title={overview?.manifest?.label || id}
        description={overview ? `${overview.estate?.workloads ?? 0} workloads${overview.meta?.richness?.label ? ` · ${overview.meta.richness.label}` : ''}` : <SkeletonText>40 workloads · Enough to price</SkeletonText>}
        actions={overview ? <Badge variant={overview.finalised ? 'success' : gate?.ready ? 'success' : 'warning'}>{overview.finalised ? 'Final' : gate?.ready ? 'Ready to finalise' : `Draft · ${gate?.open ?? 0} open`}</Badge> : null}
      />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <NameField name={actor.name} setName={actor.setName} />
        <Button size="sm" variant="secondary" onClick={() => void load().then(() => toast({ title: 'Refreshed.', variant: 'success' })).catch(() => toast({ title: 'Could not refresh.', variant: 'danger' }))}>Refresh</Button>
      </div>
      {error ? <Notice tone="danger" title="This run could not be opened">{error}</Notice> : null}
      {!overview && !error ? <div role="status" aria-label="Loading the run">{Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="mb-2 h-8 w-full" />)}</div> : null}
      {overview ? (
        <>
          <PackageStepper stage={current} busy={busy} onPick={(next) => navigate('run', { id, stage: next })} />
          {current === 'overview' ? <OverviewStage overview={overview} onAws={() => navigate('run', { id, stage: 'transform' })} onEstimate={() => void act('/run_estimate', {}, 'Offline estimate ready.')} /> : null}
          {current === 'transform' ? <AwsStage id={id} actor={actor.name} canAct={Boolean(actor.name)} onAct={(path, body, ok) => act(path, body, ok)} /> : null}
          {current === 'workloads' ? <WorkloadsStage id={id} /> : null}
          {current === 'licensing' ? <LicensingStage id={id} /> : null}
          {current === 'exceptions' ? <ExceptionsStage id={id} canAct={Boolean(actor.name)} onAck={(body, ok) => void act('/ack', body, ok)} /> : null}
          {current === 'agent' ? <AgentStage id={id} busy={busy} canAct={Boolean(actor.name)} onRun={(task, mode) => void act('/agent', { task, mode }, 'The proposals are ready to review.')} onDecide={(body, ok) => void act('/decide', body, ok)} /> : null}
          {current === 'review' ? <ReviewStage overview={overview} canAct={Boolean(actor.name)} onAct={(path, body, ok) => void act(path, body, ok)} onFinalise={(rounds) => setConfirmFinal(rounds)} /> : null}
          {current === 'outputs' ? <OutputsStage id={id} canAct={Boolean(actor.name)} onExport={(template) => void act('/export', { template, pdf: true }, 'Files created.')} /> : null}
          {current === 'audit' ? <AuditStage id={id} /> : null}
        </>
      ) : null}
      <Modal
        open={confirmFinal !== null}
        onOpenChange={(open) => { if (!open) setConfirmFinal(null); }}
        title="Finalise and lock this package?"
        description="Finalising locks the figures and the decisions. You can reopen it later, with a reason."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmFinal(null)}>Not yet</Button>
            <Button onClick={() => { const rounds = confirmFinal ?? 0; setConfirmFinal(null); void act('/finalise', { rework_rounds: rounds }, 'Finalised and locked.'); }}>Finalise</Button>
          </>
        }
      />
    </div>
  );
}
