'use client';

import { useCallback, useEffect, useState } from 'react';

import { ApiError, mraRequest } from '@/features/mra/api';
import { NameField, useActor } from '@/features/mra/actor';
import { when } from '@/features/mra/bits';
import { ReviewStepper } from '@/features/mra/stepper';
import { ActivitiesStage, AnswersStage, OutputsStage, OverviewStage, ProposalsStage, RatingsStage, ReleaseStage, ValidationStage } from '@/features/mra/stages';
import { MRA_STAGES, type MraInfo, type MraRun, type MraStage } from '@/features/mra/types';
import type { Navigate } from '@/features/agents/types';
import { Notice } from '@/shared/components/notice';
import { PageHeader } from '@/shared/components/page-header';
import { Badge } from '@/shared/design-system/ui/badge';
import { Button } from '@/shared/design-system/ui/button';
import { Skeleton, SkeletonText } from '@/shared/design-system/ui/skeleton';
import { useToast } from '@/shared/design-system/ui/toaster';

function isStage(value: string): value is MraStage {
  return MRA_STAGES.some((item) => item.id === value);
}

export function RunScreen({ id, stage, navigate }: { id: string; stage: string; navigate: Navigate }) {
  const toast = useToast();
  const actor = useActor();
  const current = isStage(stage) ? stage : 'overview';
  const [run, setRun] = useState<MraRun | null>(null);
  const [info, setInfo] = useState<MraInfo | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const next = await mraRequest<MraRun>('GET', `/runs/${encodeURIComponent(id)}`);
    setRun(next);
    setError('');
  }, [id]);

  useEffect(() => {
    let live = true;
    setRun(null);
    load().catch((caught) => {
      if (!live) return;
      setError(caught instanceof Error ? caught.message : 'The run could not be loaded.');
    });
    mraRequest<MraInfo>('GET', '/info').then((value) => { if (live) setInfo(value); }).catch(() => undefined);
    return () => { live = false; };
  }, [load]);

  const save = async (path: string, body: unknown, ok: string) => {
    if (!actor.name) {
      toast({ title: 'Enter your name so this decision is recorded against you.', variant: 'warning' });
      return;
    }
    setBusy(true);
    try {
      await mraRequest('POST', path, body);
      if (path.endsWith('/purge')) {
        toast({ title: ok, variant: 'success' });
        navigate('runs');
        return;
      }
      await load();
      toast({ title: ok, variant: path.endsWith('/agent') ? 'success' : 'success' });
    } catch (caught) {
      const warning = caught instanceof ApiError && caught.status === 401;
      toast({ title: caught instanceof Error ? caught.message : 'That did not work.', variant: warning ? 'danger' : 'danger' });
    } finally {
      setBusy(false);
    }
  };

  const title = MRA_STAGES.find((item) => item.id === current)?.label ?? 'Run';
  const canWrite = info?.user?.can_write !== false;
  return (
    <div className="space-y-4">
      <PageHeader
        eyebrow="Readiness"
        title={run ? run.customer : 'Run'}
        description={run ? `${run.set_id} · ${when(run.generated_at)}` : <SkeletonText>R-0000 · 29 Oct 2026, 11:00</SkeletonText>}
        actions={run ? <Badge variant={run.status?.final ? 'success' : 'warning'}>{run.report_status}</Badge> : null}
      />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <NameField name={actor.name} setName={actor.setName} />
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => void load().then(() => toast({ title: 'Refreshed.', variant: 'success' })).catch((caught) => toast({ title: caught instanceof Error ? caught.message : 'Could not refresh.', variant: 'danger' }))}>Refresh</Button>
      </div>
      {info?.user && !info.user.can_write ? <Notice tone="info" title="This account can read but not change anything." /> : null}
      {error ? <Notice tone="danger" title="This run could not be opened">{error}</Notice> : null}
      {!run && !error ? (
        <div role="status" aria-label="Loading the run">
          {Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="mb-2 h-8 w-full" />)}
        </div>
      ) : null}
      {run ? (
        <>
          <ReviewStepper stage={current} run={run} busy={busy} onPick={(next) => navigate('run', { id, stage: next })} />
          {current === 'overview' ? <OverviewStage run={run} onRatings={() => navigate('run', { id, stage: 'ratings' })} /> : null}
          {current === 'ratings' ? <RatingsStage run={run} canWrite={canWrite} onSaved={save} /> : null}
          {current === 'activities' ? <ActivitiesStage run={run} canWrite={canWrite} onSaved={save} /> : null}
          {current === 'validation' ? <ValidationStage run={run} canWrite={canWrite} onSaved={save} /> : null}
          {current === 'proposals' ? <ProposalsStage run={run} busy={busy} canWrite={canWrite} onSaved={save} /> : null}
          {current === 'answers' ? <AnswersStage run={run} /> : null}
          {current === 'release' ? <ReleaseStage run={run} canWrite={canWrite} onSaved={save} /> : null}
          {current === 'outputs' ? <OutputsStage run={run} canWrite={canWrite} onSaved={save} /> : null}
        </>
      ) : null}
      <p className="sr-only">{title}</p>
    </div>
  );
}
