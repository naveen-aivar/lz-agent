'use client';

import { useEffect, useState } from 'react';

import { ApiError, tcoApi, type Job, type OutputFile, type Summary } from '@/features/tco/api';
import { buildMapAnswer } from '@/features/tco/map';
import { buildLicensingAnswer, EMPTY_LICENSING, type LicensingForm } from '@/features/tco/licensing';
import { LicensingCard, LicensingFields } from '@/features/tco/licensing-panels';
import { CalculatorCard } from '@/features/tco/calculator-card';
import { HandoverCard } from '@/features/tco/handover-card';
import { MapCard } from '@/features/tco/map-card';
import { buildParameters, DEFAULT_SETTINGS, type SettingValues } from '@/features/tco/parameters';
import { SettingsFields } from '@/features/tco/settings-fields';
import { QuestionForm } from '@/features/tco/question';
import { DeckPreview } from '@/features/tco/deck-preview';
import { ActivityTimeline, DownloadCards } from '@/features/tco/detail-panels';
import { AssessmentStepper } from '@/features/tco/stepper';
import {
  elapsed,
  formatDate,
  formatMoney,
  isActive,
  PROGRESS_TEXT,
  statusLabel,
  TERMINAL,
} from '@/features/tco/format';
import type { Navigate } from '@/features/agents/types';
import { Notice } from '@/shared/components/notice';
import { PageHeader } from '@/shared/components/page-header';
import { Badge } from '@/shared/design-system/ui/badge';
import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';
import { SkeletonText } from '@/shared/design-system/ui/skeleton';
import { useToast } from '@/shared/design-system/ui/toaster';

const PAGE_SIZE = 20;
const SKELETON_ROWS = 15;
const MAX_BYTES = 100 * 1024 * 1024;

function toneOf(status: string): 'success' | 'warning' | 'danger' | 'default' | 'muted' {
  if (status === 'COMPLETED') return 'success';
  if (status === 'FAILED') return 'danger';
  if (status === 'NEEDS_INPUT') return 'warning';
  if (TERMINAL.has(status)) return 'muted';
  return 'default';
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.';
}

export function AssessmentList({ navigate }: { navigate: Navigate }) {
  const toast = useToast();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async (reset: boolean) => {
    setError('');
    try {
      const page = await tcoApi.listJobs({ limit: PAGE_SIZE, cursor: reset ? null : cursor });
      setJobs((current) => (reset ? page.data : current.concat(page.data)));
      setCursor(page.next_cursor);
    } catch (caught) {
      setError(messageOf(caught));
      if (caught instanceof ApiError && caught.status === 401) toast({ title: 'Sign in again to use this.', variant: 'danger' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(true);
    // The first page only. Load more is explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const count = (pred: (status: string) => boolean) => jobs.filter((job) => pred(job.status)).length;
  const tiles = [
    { label: 'Assessments', value: String(jobs.length), hint: cursor ? 'Loaded so far' : 'On this page' },
    { label: 'In progress', value: String(count((status) => isActive(status) && status !== 'NEEDS_INPUT')) },
    { label: 'Need an answer', value: String(count((status) => status === 'NEEDS_INPUT')) },
    { label: 'Completed', value: String(count((status) => status === 'COMPLETED')), hint: count((status) => status === 'FAILED') ? `${count((status) => status === 'FAILED')} failed` : '' },
  ];

  return (
    <div className="view-enter">
      <PageHeader
        title="Assessments"
        description="Upload an inventory file, answer any questions, and compare today’s cost with AWS."
        actions={<Button onClick={() => navigate('new')} disabled={loading}>New assessment</Button>}
      />
      {error ? (
        <Notice tone="danger" title="The assessments could not be loaded." className="mt-4">
          <p>{error}</p>
        </Notice>
      ) : null}
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {tiles.map((tile, index) => (
          <Card key={tile.label} className="animate-fade-up p-4" style={{ ['--stagger' as string]: index }}>
            <p className="text-sm text-[var(--color-gray-500)]">{tile.label}</p>
            <p className="mt-1 text-2xl font-semibold">{loading ? <SkeletonText>00</SkeletonText> : tile.value}</p>
            {tile.hint ? <p className="mt-1 text-xs text-[var(--color-gray-500)]">{tile.hint}</p> : null}
          </Card>
        ))}
      </div>
      <Card className="mt-4 overflow-hidden">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">All assessments</caption>
          <thead className="bg-[var(--color-gray-50)] text-[var(--color-gray-500)]">
            <tr>
              <th className="px-4 py-3 font-medium" scope="col">File</th>
              <th className="px-4 py-3 font-medium" scope="col">Status</th>
              <th className="px-4 py-3 font-medium" scope="col">Reference</th>
              <th className="px-4 py-3 font-medium" scope="col">Created</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: SKELETON_ROWS }, (_, index) => (
                <tr key={index} className="border-t border-[var(--color-gray-100)]">
                  <td className="px-4 py-3"><SkeletonText className="font-medium">inventory-export.xlsx</SkeletonText></td>
                  <td className="px-4 py-3"><SkeletonText>In progress</SkeletonText></td>
                  <td className="px-4 py-3"><SkeletonText>ACME-1042</SkeletonText></td>
                  <td className="px-4 py-3"><SkeletonText>28 Oct 2026, 15:27</SkeletonText></td>
                </tr>
              ))
            ) : jobs.length === 0 ? (
              <tr><td className="px-4 py-6 text-[var(--color-gray-500)]" colSpan={4}>No assessments yet.</td></tr>
            ) : (
              jobs.map((job) => (
                <tr key={job.job_id} className="cursor-pointer border-t border-[var(--color-gray-100)] hover:bg-[var(--color-gray-50)]" onClick={() => navigate('job', { id: job.job_id })}>
                  <td className="px-4 py-3">
                    <button type="button" className="font-medium text-[var(--color-primary-700)]" onClick={() => navigate('job', { id: job.job_id })}>
                      {job.original_filename || job.job_id}
                    </button>
                  </td>
                  <td className="px-4 py-3"><Badge variant={toneOf(job.status)}>{statusLabel(job.status)}</Badge></td>
                  <td className="px-4 py-3">{job.customer_ref || ''}</td>
                  <td className="px-4 py-3">{formatDate(job.created_at)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {cursor ? <div className="border-t border-[var(--color-gray-100)] p-3"><Button variant="secondary" size="sm" onClick={() => void load(false)}>Load more</Button></div> : null}
      </Card>
    </div>
  );
}

export function NewAssessment({ navigate }: { navigate: Navigate }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [customer, setCustomer] = useState('');
  const [settings, setSettings] = useState<SettingValues>(DEFAULT_SETTINGS);
  const [mapOn, setMapOn] = useState(false);
  const [licensingOn, setLicensingOn] = useState(false);
  const [licensing, setLicensing] = useState<LicensingForm>(EMPTY_LICENSING);
  const [choice, setChoice] = useState('');
  const [ec2, setEc2] = useState('');
  const [ebs, setEbs] = useState('');
  const [years, setYears] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    void tcoApi
      .health()
      .then((health) => {
        setMapOn(health?.features?.map_credits === 'ask');
        setLicensingOn(health?.features?.licensing === 'ask');
      })
      .catch(() => {
        setMapOn(false);
        setLicensingOn(false);
      });
  }, []);

  return (
    <div className="view-enter">
      <PageHeader title="New assessment" description="The inventory file is an Excel export. Optional settings can be confirmed later." />
      <Card className="mt-4 p-5">
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            setError('');
            if (!file) return setError('Choose the inventory file first.');
            if (!/\.(xlsx|xls)$/i.test(file.name)) return setError('Only Excel files (.xlsx or .xls) are supported.');
            if (file.size > MAX_BYTES) return setError('That file is too large.');
            const mapEntry = mapOn ? buildMapAnswer({ choice, ec2, ebs, years }) : { answer: null };
            if (mapEntry.error) return setError(mapEntry.error);
            const licensingEntry = licensingOn ? buildLicensingAnswer(licensing) : { answer: null };
            if (licensingEntry.error) return setError(licensingEntry.error);
            const statement = licensingEntry.answer?.has_statement ? licensing.statement : null;
            if (statement && statement.size > MAX_BYTES) return setError('The licence statement is too large.');
            const built = buildParameters(settings);
            if (built.error) return setError(built.error);
            const parameters = built.parameters;
            setBusy(true);
            void (async () => {
              try {
                const created = await tcoApi.createJob({
                  filename: file.name,
                  size_bytes: file.size,
                  customer_ref: customer.trim() || undefined,
                  parameters,
                  map: mapEntry.answer ?? undefined,
                  licensing: licensingEntry.answer ?? undefined,
                  statement_filename: statement?.name,
                  statement_size_bytes: statement?.size,
                });
                await tcoApi.uploadFile(created.upload, file);
                if (statement && created.statement_upload) await tcoApi.uploadFile(created.statement_upload, statement);
                await tcoApi.startJob(created.job_id);
                toast({ title: 'The assessment has started.', variant: 'success' });
                navigate('job', { id: created.job_id });
              } catch (caught) {
                setError(messageOf(caught));
                toast({ title: 'The assessment could not be started.', description: messageOf(caught), variant: 'danger' });
              } finally {
                setBusy(false);
              }
            })();
          }}
        >
          <div>
            <label htmlFor="inventory" className="text-sm font-medium">Inventory file</label>
            <input id="inventory" className="mt-2 block w-full text-sm" type="file" accept=".xlsx,.xls" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </div>
          <div>
            <label htmlFor="customer" className="text-sm font-medium">Customer or reference <span className="text-[var(--color-gray-500)]">(optional)</span></label>
            <input id="customer" className="mt-2 w-full rounded-[var(--radius-md)] border border-[var(--color-gray-200)] px-3 py-2 text-sm" maxLength={120} value={customer} onChange={(event) => setCustomer(event.target.value)} />
          </div>
          <SettingsFields values={settings} setValues={setSettings} />
          {mapOn ? (
            <fieldset className="grid gap-3">
              <legend className="text-sm font-medium">Migration credits (optional)</legend>
              <p className="text-sm text-[var(--color-gray-500)]">If the customer is in the AWS Migration Acceleration Program, the results can show those credits.</p>
              <div role="radiogroup" aria-label="Is the customer enrolled?" className="grid gap-2 text-sm">
                {[
                  ['', 'Not specified'],
                  ['yes', 'Yes, enrolled'],
                  ['no', 'No'],
                ].map(([value, label]) => (
                  <label key={label} className="flex items-center gap-2">
                    <input type="radio" name="map" value={value} checked={choice === value} onChange={() => setChoice(value)} /> {label}
                  </label>
                ))}
              </div>
              {choice === 'yes' ? (
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="text-sm">Compute credit (%)<input className="mt-1 w-full rounded-[var(--radius-md)] border px-3 py-2" type="number" min={0} max={100} value={ec2} onChange={(event) => setEc2(event.target.value)} /></label>
                  <label className="text-sm">Storage credit (%)<input className="mt-1 w-full rounded-[var(--radius-md)] border px-3 py-2" type="number" min={0} max={100} value={ebs} onChange={(event) => setEbs(event.target.value)} /></label>
                  <label className="text-sm">Years (1 to 5)<input className="mt-1 w-full rounded-[var(--radius-md)] border px-3 py-2" type="number" min={1} max={5} value={years} onChange={(event) => setYears(event.target.value)} /></label>
                </div>
              ) : null}
            </fieldset>
          ) : null}
          {licensingOn ? <LicensingFields form={licensing} setForm={setLicensing} /> : null}
          {error ? <p className="text-sm text-[var(--color-danger-700)]" role="alert">{error}</p> : null}
          <div><Button type="submit" loading={busy}>Upload and start</Button></div>
        </form>
      </Card>
    </div>
  );
}

function AssessmentSkeleton() {
  return (
    <div aria-busy="true">
      <p className="sr-only">Loading the assessment</p>
      <PageHeader
        title={<SkeletonText>inventory-export.xlsx</SkeletonText>}
        description={<SkeletonText>Created 28 Oct 2026, 5:11 PM · Updated 28 Oct 2026, 5:20 PM</SkeletonText>}
        meta={<SkeletonText>Completed</SkeletonText>}
      />
      <ol className="mt-4 mb-6 flex flex-wrap gap-2" aria-hidden>
        {['Upload', 'Read the inventory', 'Your answers', 'Compare costs', 'Results'].map((label, index) => (
          <li key={label} className="flex items-center gap-2 text-sm">
            <span className="grid h-6 w-6 place-items-center rounded-full border border-[var(--color-gray-200)] text-xs text-[var(--color-gray-500)]">{index + 1}</span>
            <span>{label}</span>
          </li>
        ))}
      </ol>
      <div className="mb-4 flex gap-2" aria-hidden>
        {['Overview', 'Downloads', 'Timeline'].map((name) => (
          <span key={name} className="rounded-full px-3 py-1.5 text-sm text-[var(--color-gray-700)]">{name}</span>
        ))}
      </div>
      <Card className="p-5">
        <h2 className="text-lg font-semibold">Results</h2>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {['Servers in scope', 'Storage volumes in scope', 'Recommended AWS per year'].map((label) => (
            <div key={label}>
              <p className="text-sm text-[var(--color-gray-500)]">{label}</p>
              <SkeletonText>000 of 000</SkeletonText>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Results({ summary }: { summary: Summary }) {
  const models = summary.pricing_models ?? [];
  const best = models.find((model) => model.recommended) ?? models[0];
  const max = Math.max(1, ...models.map((model) => model.annual_aws_cost || 0));
  return (
    <Card className="mt-4 p-5">
      <h2 className="text-lg font-semibold">Results</h2>
      <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
        <div><dt className="text-[var(--color-gray-500)]">Servers in scope</dt><dd>{summary.servers_in_scope != null ? `${summary.servers_in_scope} of ${summary.servers_total}` : 'Not available'}</dd></div>
        <div><dt className="text-[var(--color-gray-500)]">Storage volumes in scope</dt><dd>{summary.volumes_in_scope != null ? `${summary.volumes_in_scope} of ${summary.volumes_total}` : 'Not available'}</dd></div>
        <div><dt className="text-[var(--color-gray-500)]">Recommended AWS per year</dt><dd>{best ? `${formatMoney(best.annual_aws_cost)} · ${best.name}` : 'Not available'}</dd></div>
      </dl>
      <ul className="mt-4 grid gap-3" aria-label="AWS cost per year by pricing model">
        {models.map((model) => (
          <li key={model.name}>
            <div className="flex justify-between text-sm"><span>{model.name}{model.recommended ? ' · recommended' : ''}</span><span>{formatMoney(model.annual_aws_cost)}</span></div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-[var(--color-gray-100)]" aria-hidden><div className="h-full bg-[var(--color-primary-600)]" style={{ width: `${((model.annual_aws_cost || 0) / max) * 100}%` }} /></div>
          </li>
        ))}
      </ul>
      {summary.capacity_description ? <p className="mt-3 text-sm text-[var(--color-gray-500)]">{summary.capacity_description}</p> : null}
    </Card>
  );
}

export function AssessmentDetail({ id }: { id: string }) {
  const toast = useToast();
  const [job, setJob] = useState<Job | null>(null);
  const [files, setFiles] = useState<OutputFile[]>([]);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'overview' | 'downloads' | 'timeline'>('overview');
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let stop = false;
    let timer = 0;
    const pull = async () => {
      try {
        const next = await tcoApi.getJob(id);
        if (stop) return null;
        setJob(next);
        setError('');
        if (next.status === 'COMPLETED') {
          try {
            const outputs = await tcoApi.jobOutputs(id);
            if (!stop) setFiles(outputs.files);
          } catch (caught) {
            if (!stop) setError(messageOf(caught));
          }
        }
        return next;
      } catch (caught) {
        if (!stop) setError(messageOf(caught));
        return null;
      }
    };
    const loop = async () => {
      const next = await pull();
      if (stop || !next) {
        if (!stop && !next) timer = window.setTimeout(() => void loop(), 5000);
        return;
      }
      if (TERMINAL.has(next.status)) return;
      timer = window.setTimeout(() => {
        if (document.hidden) {
          timer = window.setTimeout(() => void loop(), 2000);
          return;
        }
        setNow(Date.now());
        void loop();
      }, 2000);
    };
    void loop();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [id]);

  if (error && !job) {
    return <Notice tone="danger" title="This assessment could not be opened." className="mt-4"><p>{error}</p></Notice>;
  }
  if (!job) return <AssessmentSkeleton />;
  const running = isActive(job.status) || job.status === 'NEEDS_INPUT';
  const summary = job.status === 'COMPLETED' ? job.summary : undefined;
  const deckPdf = files.find((file) => file.label === 'deck_pdf');

  return (
    <div>
      <PageHeader
        title={job.original_filename || 'Assessment'}
        description={`Created ${formatDate(job.created_at)}${job.updated_at ? ` · Updated ${formatDate(job.updated_at)}` : ''}`}
        meta={<Badge variant={toneOf(job.status)}>{statusLabel(job.status)}</Badge>}
      />
      <div className="mt-4">
        <AssessmentStepper status={job.status} />
      </div>
      {running && job.status !== 'NEEDS_INPUT' ? (
        <p className="mb-4 text-sm text-[var(--color-gray-700)]" aria-live="polite">
          {PROGRESS_TEXT[job.status] ?? 'Working.'} Elapsed {elapsed(job.created_at, now)}.
        </p>
      ) : null}
      {job.status === 'FAILED' ? (
        <Notice tone="danger" title="This assessment failed." className="mb-4"><p>{job.error_message || 'It stopped before the results were ready.'}</p></Notice>
      ) : null}
      {job.status === 'NEEDS_INPUT' && job.pending_input ? (
        <QuestionForm
          key={job.pending_input.request_id}
          pending={job.pending_input}
          onSubmit={async (answer) => {
            await tcoApi.answerJob(id, answer);
            toast({ title: 'Answer sent.', variant: 'success' });
            setJob(await tcoApi.getJob(id));
          }}
        />
      ) : null}
      <div role="tablist" aria-label="Assessment sections" className="mb-4 flex gap-2">
        {(['overview', 'downloads', 'timeline'] as const).map((name) => (
          <button key={name} type="button" role="tab" aria-selected={tab === name} className={`rounded-full px-3 py-1.5 text-sm ${tab === name ? 'bg-[var(--color-primary-50)] font-medium text-[var(--color-primary-700)]' : 'text-[var(--color-gray-700)]'}`} onClick={() => setTab(name)}>
            {name === 'overview' ? 'Overview' : name === 'downloads' ? 'Downloads' : 'Timeline'}
          </button>
        ))}
      </div>
      <div className="view-enter" key={tab}>
      {tab === 'overview' ? (
        summary ? (
          <>
            <Results summary={summary} />
            {deckPdf ? <DeckPreview url={deckPdf.url} /> : null}
            {summary.calculator ? <CalculatorCard calculator={summary.calculator} /> : null}
            {summary.licensing ? <LicensingCard licensing={summary.licensing} /> : null}
            {summary.map ? <MapCard map={summary.map} /> : null}
            {summary.handover ? <HandoverCard handover={summary.handover} /> : null}
          </>
        ) : (
          <p className="text-sm text-[var(--color-gray-500)]">{job.status === 'FAILED' ? 'There are no results because the assessment failed.' : 'Results and the deck appear here when the assessment finishes.'}</p>
        )
      ) : null}
      {tab === 'downloads' ? (
        files.length ? (
          <DownloadCards files={files} />
        ) : (
          <p className="text-sm text-[var(--color-gray-500)]">{job.status === 'FAILED' ? 'There are no files because the assessment failed.' : 'Files are ready to download when the assessment finishes. Links expire after a few minutes.'}</p>
        )
      ) : null}
      {tab === 'timeline' ? <ActivityTimeline events={job.events ?? []} running={running} /> : null}
      </div>
    </div>
  );
}
