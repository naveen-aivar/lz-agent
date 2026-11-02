'use client';

import { useState } from 'react';

import { mraRequest } from '@/features/mra/api';
import { colourLabel, colourVariant, ScoreTable, when } from '@/features/mra/bits';
import { ReadinessMark } from '@/features/mra/readiness';
import type { MraProposal, MraQuestion, MraRun, MraValidation } from '@/features/mra/types';
import { Notice } from '@/shared/components/notice';
import { controlClass } from '@/shared/components/form-controls';
import { Badge } from '@/shared/design-system/ui/badge';
import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';
import { Modal } from '@/shared/design-system/ui/modal';

export function OverviewStage({ run, onRatings }: { run: MraRun; onRatings: () => void }) {
  const focus = run.focus;
  const sentences = [...(focus?.perspective_sentences ?? []), ...(focus?.workstream_sentences ?? [])];
  const rated = (run.questions ?? []).filter((question) => question.perspective && question.score !== null).length;
  const scored = (run.questions ?? []).filter((question) => question.perspective).length;
  return (
    <div className="view-enter space-y-4">
      <div className="flex items-center gap-4">
        <ReadinessMark done={rated} total={scored} />
        <p className="text-sm text-[var(--color-gray-700)]">{run.narrative?.text}</p>
      </div>
      {run.blank_ratings?.length ? (
        <Notice tone="warning" title={`${run.blank_ratings.length} rating${run.blank_ratings.length === 1 ? '' : 's'} still blank`}>
          <p>{run.blank_ratings.join(', ')}. Groups that contain them show as Incomplete.</p>
          <Button size="sm" variant="secondary" className="mt-2" onClick={onRatings}>Give them a rating</Button>
        </Notice>
      ) : null}
      {run.input_warnings?.length ? (
        <Notice tone="info" title="Notes from reading the questionnaire">
          <ul className="list-disc pl-4">{run.input_warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </Notice>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4"><ScoreTable title="Perspectives" rows={run.perspectives ?? []} /></Card>
        <Card className="p-4"><ScoreTable title="Workstreams" rows={run.workstreams ?? []} /></Card>
      </div>
      <Card className="space-y-3 p-4">
        <h3 className="text-sm font-semibold">What the readout will say</h3>
        <ul className="list-disc space-y-1 pl-4 text-sm">{sentences.map((sentence) => <li key={sentence}>{sentence}</li>)}</ul>
        <div className="grid gap-4 sm:grid-cols-2">
          <div><p className="text-sm font-medium">Strengths</p><ul className="list-disc pl-4 text-sm">{(focus?.strengths ?? []).map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div><p className="text-sm font-medium">Gaps</p><ul className="list-disc pl-4 text-sm">{(focus?.gaps ?? []).map((item) => <li key={item}>{item}</li>)}</ul></div>
        </div>
      </Card>
      <p className="text-sm text-[var(--color-gray-500)]">
        {run.traceability?.evidenced ?? 0} of {run.traceability?.scored_questions ?? 0} rated questions have supporting evidence
        {run.traceability?.evidenced_pct != null ? ` (${run.traceability.evidenced_pct}%).` : '.'}
        {run.notes?.length ? '' : ' No interview notes were uploaded.'}
      </p>
    </div>
  );
}

function RatingForm({ run, question, label, canWrite, onSaved }: { run: MraRun; question: MraQuestion; label: string; canWrite: boolean; onSaved: (path: string, body: unknown, ok: string) => void }) {
  const [chosen, setChosen] = useState(question.score ?? 0);
  const [reason, setReason] = useState('');
  return (
    <div className="space-y-3">
      <div className="space-y-2">
        {question.levels.map((text, index) => {
          const level = index + 1;
          return (
            <label key={level} className={`flex gap-2 rounded-[var(--radius-md)] border p-2 text-sm ${chosen === level ? 'border-[var(--color-primary-600)] bg-[var(--color-primary-25)]' : 'border-[var(--color-gray-100)]'}`}>
              <input type="radio" name={`lv-${question.question_id}`} checked={chosen === level} onChange={() => setChosen(level)} />
              <span>{text}</span>
            </label>
          );
        })}
      </div>
      <label className="block text-sm">Reason<textarea className={`${controlClass} mt-1`} rows={2} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Why this level matches" /></label>
      <Button
        size="sm"
        disabled={!canWrite || !chosen}
        onClick={() => onSaved(`/runs/${encodeURIComponent(run.set_id)}/adjust`, { question: question.question_id, score: chosen, reason }, `${question.question_id} set to ${chosen}. Confirm the scores again before release.`)}
      >
        {!chosen ? 'Choose a level first' : label}
      </Button>
    </div>
  );
}

export function RatingsStage({ run, canWrite, onSaved }: { run: MraRun; canWrite: boolean; onSaved: (path: string, body: unknown, ok: string) => void }) {
  const names = Object.fromEntries((run.activities ?? []).map((activity) => [activity.id, activity.name]));
  const scored = (run.questions ?? []).filter((question) => question.perspective);
  const blank = scored.filter((question) => question.score === null);
  const rest = scored.filter((question) => question.score !== null);
  return (
    <div className="view-enter space-y-4">
      <p className="text-sm text-[var(--color-gray-500)]">One agreed rating per question. A blank rating blocks release. A change is kept with your name and the reason.</p>
      {blank.length === 0 ? <Notice tone="success" title="Every scored question has a rating" /> : null}
      {blank.map((question) => (
        <Card key={question.question_id} className="space-y-2 p-4">
          <p className="text-sm font-semibold">{question.question_id} · {question.category} · {names[question.activity] || ''}</p>
          <p className="text-sm">{question.text}</p>
          <RatingForm run={run} question={question} label="Set this rating" canWrite={canWrite} onSaved={onSaved} />
        </Card>
      ))}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-[var(--color-gray-500)]">{['Question', 'Rating', 'What that level says', 'Evidence', ''].map((heading) => <th key={heading || 'action'} className="py-2 pr-3 font-medium">{heading}</th>)}</tr>
          </thead>
          <tbody>
            {rest.map((question) => (
              <tr key={question.question_id} className="border-t border-[var(--color-gray-100)] align-top">
                <td className="py-2 pr-3">{question.question_id}. {question.text}</td>
                <td className="py-2 pr-3">{question.score}{question.adjusted ? <Badge variant="muted">adjusted from {question.original_score}</Badge> : null}</td>
                <td className="py-2 pr-3">{question.level_text}</td>
                <td className="py-2 pr-3">{question.traceable ? 'yes' : 'none'}</td>
                <td className="py-2"><details><summary>Change</summary><RatingForm run={run} question={question} label="Change this rating" canWrite={canWrite} onSaved={onSaved} /></details></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ActivitiesStage({ run, canWrite, onSaved }: { run: MraRun; canWrite: boolean; onSaved: (path: string, body: unknown, ok: string) => void }) {
  const groups = new Map<string, MraRun['activities']>();
  for (const activity of run.activities ?? []) {
    const list = groups.get(activity.workstream_name) ?? [];
    list.push(activity);
    groups.set(activity.workstream_name, list);
  }
  return (
    <div className="view-enter space-y-4">
      <p className="text-sm text-[var(--color-gray-500)]">Nothing here is final until you decide. Approve, rewrite, or reject each proposed action.</p>
      {[...groups.entries()].map(([name, list]) => (
        <section key={name} className="space-y-3">
          <h3 className="text-sm font-semibold">{name}</h3>
          {list.map((activity) => <ActivityCard key={activity.id} run={run} activity={activity} canWrite={canWrite} onSaved={onSaved} />)}
        </section>
      ))}
    </div>
  );
}

function ActivityCard({ run, activity, canWrite, onSaved }: { run: MraRun; activity: MraRun['activities'][number]; canWrite: boolean; onSaved: (path: string, body: unknown, ok: string) => void }) {
  const first = activity.actions[0];
  const [decision, setDecision] = useState(activity.decision === 'edit' || activity.decision === 'reject' ? activity.decision : 'approve');
  const [text, setText] = useState('');
  const [owner, setOwner] = useState(first?.owner || '');
  const [due, setDue] = useState(first?.due_date || '');
  const [comment, setComment] = useState(activity.comment || '');
  return (
    <Card className="space-y-2 p-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <strong>{activity.id} {activity.name}</strong>
        <Badge variant={colourVariant(activity.colour)}>{colourLabel(activity.colour)}</Badge>
        <span>{activity.phase}</span>
      </div>
      <p className="text-sm">{activity.observation?.text}</p>
      {activity.needs_action ? (
        <>
          <ul className="list-disc pl-4 text-sm">{activity.actions.map((action) => <li key={action.text}>{action.text} · {action.owner || 'owner not set'} · {action.due_date || 'date not set'}</li>)}</ul>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">Decision<select className={`${controlClass} mt-1`} value={decision} onChange={(event) => setDecision(event.target.value)}><option value="approve">Approve</option><option value="edit">Approve with my own wording</option><option value="reject">Reject</option></select></label>
            <label className="text-sm">Owner<input className={`${controlClass} mt-1`} value={owner} onChange={(event) => setOwner(event.target.value)} /></label>
            <label className="text-sm">Due date<input className={`${controlClass} mt-1`} type="date" value={due} onChange={(event) => setDue(event.target.value)} /></label>
            <label className="text-sm">Comment<input className={`${controlClass} mt-1`} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Required to reject" /></label>
            <label className="text-sm sm:col-span-2">Wording<textarea className={`${controlClass} mt-1`} rows={2} value={text} onChange={(event) => setText(event.target.value)} placeholder="Only used with your own wording" /></label>
          </div>
          <Button size="sm" disabled={!canWrite || (decision === 'reject' && !comment.trim())} onClick={() => onSaved(`/runs/${encodeURIComponent(run.set_id)}/decide`, { activity: activity.id, decision, text, owner, due_date: due, comment }, `Decision saved for ${activity.name}.`)}>
            {decision === 'reject' && !comment.trim() ? 'Add a comment to reject' : 'Save decision'}
          </Button>
        </>
      ) : <p className="text-sm text-[var(--color-gray-500)]">No action required.</p>}
    </Card>
  );
}

export function ValidationStage({ run, canWrite, onSaved }: { run: MraRun; canWrite: boolean; onSaved: (path: string, body: unknown, ok: string) => void }) {
  const [filter, setFilter] = useState('open');
  const kinds = ['open', 'all', ...new Set((run.validation ?? []).map((item) => item.kind))];
  const rows = (run.validation ?? []).filter((item) => (filter === 'all' ? true : filter === 'open' ? item.resolution === 'open' : item.kind === filter));
  return (
    <div className="view-enter space-y-3">
      <p className="text-sm text-[var(--color-gray-500)]">Every rated question is either backed by a note or listed here. Resolving one needs a note.</p>
      <div className="flex flex-wrap gap-2">
        {kinds.map((kind) => <Button key={kind} size="sm" variant={kind === filter ? 'primary' : 'secondary'} onClick={() => setFilter(kind)}>{kind.replace(/_/g, ' ')}</Button>)}
      </div>
      {rows.map((item) => <ValidationCard key={item.key} run={run} item={item} canWrite={canWrite} onSaved={onSaved} />)}
      {rows.length === 0 ? <p className="text-sm text-[var(--color-gray-500)]">Nothing here.</p> : null}
    </div>
  );
}

function ValidationCard({ run, item, canWrite, onSaved }: { run: MraRun; item: MraValidation; canWrite: boolean; onSaved: (path: string, body: unknown, ok: string) => void }) {
  const [resolution, setResolution] = useState(item.resolution === 'open' ? 'accepted_risk' : item.resolution);
  const [note, setNote] = useState(item.note || '');
  return (
    <Card className="space-y-2 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <strong>{item.item_id}</strong>
        <Badge variant="muted">{item.kind.replace(/_/g, ' ')}</Badge>
        <Badge variant={item.resolution === 'open' ? 'warning' : 'success'}>{item.resolution.replace(/_/g, ' ')}</Badge>
      </div>
      <p>{item.reason}</p>
      {item.followup ? <p className="whitespace-pre-wrap text-[var(--color-gray-700)]">Follow-up for {item.followup.audience_roles.join(', ')}:{'\n'}{item.followup.questions.map((question) => `- ${question}`).join('\n')}</p> : null}
      {item.kind === 'blank_rating' ? <p className="text-[var(--color-gray-500)]">Give this a rating on the Ratings step. A note does not close it.</p> : (
        <div className="grid gap-3 sm:grid-cols-[12rem_1fr_auto] sm:items-end">
          <select className={controlClass} value={resolution} onChange={(event) => setResolution(event.target.value)} aria-label="Resolution">
            <option value="resolved">resolved</option>
            <option value="accepted_risk">accepted risk</option>
            <option value="not_applicable">not applicable</option>
          </select>
          <input className={controlClass} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Note, required" aria-label="Note" />
          <Button size="sm" disabled={!canWrite || !note.trim()} onClick={() => onSaved(`/runs/${encodeURIComponent(run.set_id)}/resolve`, { item: item.key, resolution, note }, `${item.key} resolved.`)}>{note.trim() ? 'Save' : 'Add a note first'}</Button>
        </div>
      )}
    </Card>
  );
}

export function ProposalsStage({ run, busy, canWrite, onSaved }: { run: MraRun; busy: boolean; canWrite: boolean; onSaved: (path: string, body: unknown, ok: string) => void }) {
  const [task, setTask] = useState('rating');
  const groups: [string, string][] = [['Waiting for you', 'proposed'], ['Accepted', 'accepted'], ['Rejected', 'rejected']];
  return (
    <div className="view-enter space-y-4">
      <Card className="space-y-3 p-4">
        <div className="flex items-center gap-3">
          {busy ? <ReadinessMark done={0} total={1} busy /> : null}
          <p className="text-sm text-[var(--color-gray-500)]">The assistant can only propose. Nothing changes until you accept.</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">Task
            <select className={`${controlClass} mt-1`} value={task} onChange={(event) => setTask(event.target.value)}>
              <option value="rating">Propose a rating for each blank question</option>
              <option value="evidence">Find note passages that support ratings</option>
              <option value="investigate">Draft follow-up questions</option>
              <option value="context">Extract priorities and constraints</option>
            </select>
          </label>
          <Button size="sm" disabled={!canWrite || busy} onClick={() => onSaved(`/runs/${encodeURIComponent(run.set_id)}/agent`, { task }, 'The proposals are ready to review.')}>{busy ? 'Working' : 'Run'}</Button>
        </div>
      </Card>
      {groups.map(([title, status]) => {
        const list = (run.proposals ?? []).filter((proposal) => proposal.status === status);
        if (!list.length) return null;
        return (
          <section key={status} className="space-y-3">
            <h3 className="text-sm font-semibold">{title} ({list.length})</h3>
            {list.map((proposal) => <ProposalCard key={proposal.id} run={run} proposal={proposal} canWrite={canWrite} onSaved={onSaved} />)}
          </section>
        );
      })}
      {(run.proposals ?? []).length === 0 ? <p className="text-sm text-[var(--color-gray-500)]">No proposals yet.</p> : null}
    </div>
  );
}

function ProposalCard({ run, proposal, canWrite, onSaved }: { run: MraRun; proposal: MraProposal; canWrite: boolean; onSaved: (path: string, body: unknown, ok: string) => void }) {
  const [comment, setComment] = useState('');
  const payload = proposal.payload;
  const decide = (which: 'accept' | 'reject') => onSaved(`/runs/${encodeURIComponent(run.set_id)}/proposals`, { [which]: [proposal.id], comment }, `${proposal.id} ${which === 'accept' ? 'accepted' : 'rejected'}.`);
  return (
    <Card className="space-y-2 p-4 text-sm">
      <div className="flex flex-wrap gap-2">
        <strong>{proposal.id}</strong>
        <Badge variant="muted">{proposal.kind.replace(/_/g, ' ')}</Badge>
        <Badge variant={proposal.status === 'accepted' ? 'success' : proposal.status === 'proposed' ? 'warning' : 'muted'}>{proposal.status}</Badge>
      </div>
      <ProposalBody proposal={proposal} payload={payload} />
      {proposal.excerpt ? <p className="whitespace-pre-wrap rounded-[var(--radius-md)] bg-[var(--color-gray-50)] p-2">{proposal.excerpt.found ? <>{proposal.excerpt.before}<mark>{proposal.excerpt.quote}</mark>{proposal.excerpt.after}</> : String(payload.quote || '')}</p> : null}
      <div className="flex flex-wrap items-center gap-2">
        <input className={`${controlClass} max-w-sm`} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Comment, optional" aria-label="Comment" />
        {proposal.status !== 'accepted' ? <Button size="sm" disabled={!canWrite} onClick={() => decide('accept')}>Accept</Button> : null}
        {proposal.status !== 'rejected' ? <Button size="sm" variant="secondary" disabled={!canWrite} onClick={() => decide('reject')}>{proposal.status === 'accepted' ? 'Revoke' : 'Reject'}</Button> : null}
      </div>
    </Card>
  );
}

function ProposalBody({ proposal, payload }: { proposal: MraProposal; payload: Record<string, unknown> }) {
  if (proposal.kind === 'rating') return <p><strong>{String(payload.question_id)} = {String(payload.score)}</strong>. {String(payload.rationale || '')}</p>;
  if (proposal.kind === 'evidence_link') return <p>Note {String(payload.evidence_id)} supports {String(payload.question_id)}.</p>;
  if (proposal.kind === 'context_item') return <p><strong>{String(payload.kind)}:</strong> {String(payload.text || '')}</p>;
  const questions = Array.isArray(payload.questions) ? payload.questions.map(String) : [];
  return <p>Follow-up for {String(payload.item_key)}. {questions.join(' ')}</p>;
}

export function AnswersStage({ run }: { run: MraRun }) {
  return (
    <div className="view-enter space-y-4">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead><tr className="text-[var(--color-gray-500)]">{['#', 'Category', 'Question', 'Answer'].map((heading) => <th key={heading} className="py-2 pr-3 font-medium">{heading}</th>)}</tr></thead>
          <tbody>
            {(run.text_answers ?? []).map((answer) => (
              <tr key={`${answer.number}-${answer.question}`} className="border-t border-[var(--color-gray-100)]">
                <td className="py-2 pr-3">{answer.number}</td>
                <td className="py-2 pr-3">{answer.category}</td>
                <td className="py-2 pr-3">{answer.question}</td>
                <td className="py-2">{answer.answer || 'blank'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3 className="text-sm font-semibold">Interview notes ({run.notes?.length ?? 0})</h3>
      {(run.notes ?? []).length === 0 ? <p className="text-sm text-[var(--color-gray-500)]">None uploaded.</p> : null}
      {(run.notes ?? []).map((note) => (
        <details key={note.id}><summary className="text-sm">{note.id} · {note.source}</summary><pre className="mt-2 whitespace-pre-wrap text-sm">{note.text}</pre></details>
      ))}
    </div>
  );
}

export function ReleaseStage({ run, canWrite, onSaved }: { run: MraRun; canWrite: boolean; onSaved: (path: string, body: unknown, ok: string) => void }) {
  const status = run.status;
  const [details, setDetails] = useState(run.details ?? {});
  const [reason, setReason] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmFinal, setConfirmFinal] = useState(false);
  const [typedId, setTypedId] = useState('');
  const id = encodeURIComponent(run.set_id);
  const fields = ['facilitator', 'presenter', 'workshop_date', 'readout_date', 'internal_contact', 'sponsor_contact'] as const;
  return (
    <div className="view-enter space-y-4">
      {status?.final ? <Notice tone="success" title={`Finalised by ${status.final.by} at ${when(status.final.at)}`}><p>The report is locked.</p></Notice> : status?.ready_to_finalise ? <Notice tone="success" title="Nothing is outstanding. You can finalise." /> : (
        <Notice tone="warning" title={`${status?.blockers?.length ?? 0} thing${status?.blockers?.length === 1 ? '' : 's'} still to do`}>
          <ul className="list-disc pl-4">{(status?.blockers ?? []).map((blocker) => <li key={blocker}>{blocker}</li>)}</ul>
        </Notice>
      )}
      {status?.scores_confirmation_stale ? <Notice tone="danger" title="The scores changed after they were confirmed. Confirm them again." /> : null}
      <Card className="space-y-3 p-4">
        <h3 className="text-sm font-semibold">Report details</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          {fields.map((key) => (
            <label key={key} className="text-sm capitalize">{key.replace(/_/g, ' ')}
              <input className={`${controlClass} mt-1`} type={key.endsWith('date') ? 'date' : 'text'} value={details[key] || ''} onChange={(event) => setDetails((current) => ({ ...current, [key]: event.target.value }))} />
            </label>
          ))}
        </div>
        <Button size="sm" variant="secondary" disabled={!canWrite || Boolean(status?.final)} onClick={() => onSaved(`/runs/${id}/meta`, details, 'Report details saved.')}>{status?.final ? 'Locked' : 'Save details'}</Button>
      </Card>
      <Card className="space-y-3 p-4 text-sm">
        <p>Scores confirmed: <strong>{status?.scores_confirmed ? 'yes' : 'no'}</strong>. Blank ratings: <strong>{status?.blank_ratings ?? 0}</strong>. Actions decided: <strong>{status?.actions_decided ?? 0} of {status?.actions_total ?? 0}</strong>. Validation resolved: <strong>{status?.items_resolved ?? 0} of {status?.items_total ?? 0}</strong>.</p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={!canWrite || Boolean(status?.final) || (status?.blank_ratings ?? 0) > 0} onClick={() => onSaved(`/runs/${id}/confirm`, {}, 'Scores confirmed.')}>{(status?.blank_ratings ?? 0) > 0 ? 'Fill the blank ratings first' : 'Confirm the scores'}</Button>
          <Button size="sm" disabled={!canWrite || Boolean(status?.final) || !status?.ready_to_finalise} onClick={() => setConfirmFinal(true)}>{status?.ready_to_finalise ? 'Finalise the report' : 'Not ready to finalise'}</Button>
        </div>
        {status?.final ? (
          <div className="flex flex-wrap items-end gap-2">
            <input className={`${controlClass} max-w-sm`} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Why it is being reopened" aria-label="Reason" />
            <Button size="sm" variant="secondary" disabled={!canWrite || !reason.trim()} onClick={() => onSaved(`/runs/${id}/reopen`, { reason }, 'Reopened. Confirm the scores again before finalising.')}>{reason.trim() ? 'Reopen' : 'Add a reason first'}</Button>
          </div>
        ) : null}
      </Card>
      <Button size="sm" variant="danger" disabled={!canWrite} onClick={() => setConfirmDelete(true)}>Delete this run</Button>
      <Modal open={confirmFinal} onOpenChange={setConfirmFinal} title="Finalise this report?" description="Finalising locks the scores and the decisions. You can reopen it later, with a reason." footer={
        <>
          <Button variant="secondary" onClick={() => setConfirmFinal(false)}>Not yet</Button>
          <Button onClick={() => { setConfirmFinal(false); onSaved(`/runs/${id}/finalise`, {}, 'Finalised.'); }}>Finalise</Button>
        </>
      } />
      <Modal open={confirmDelete} onOpenChange={setConfirmDelete} title="Delete this run?" description="This removes the run and its files. A record that it was deleted is kept." footer={
        <>
          <Button variant="secondary" onClick={() => setConfirmDelete(false)}>Keep it</Button>
          <Button variant="danger" disabled={typedId !== run.set_id} onClick={() => { setConfirmDelete(false); onSaved(`/runs/${id}/purge`, { confirm: typedId }, 'Deleted.'); }}>Delete</Button>
        </>
      }>
        <label className="text-sm">Type the run id to confirm<input className={`${controlClass} mt-1`} value={typedId} onChange={(event) => setTypedId(event.target.value)} /></label>
      </Modal>
    </div>
  );
}

export function OutputsStage({ run, canWrite, onSaved }: { run: MraRun; canWrite: boolean; onSaved: (path: string, body: unknown, ok: string) => void }) {
  const [kinds, setKinds] = useState({ xlsx: true, docx: true, pptx: true, context: false });
  const [template, setTemplate] = useState('');
  const kpis = run.kpis;
  const download = async (entry: MraRun['exports'][number]) => {
    const link = await mraRequest<{ url: string }>('POST', entry.url.replace(/^\/api/, '') + '/link', {});
    const anchor = document.createElement('a');
    anchor.href = link.url;
    anchor.download = entry.name;
    anchor.click();
  };
  return (
    <div className="view-enter space-y-4">
      {run.status?.final ? null : <Notice tone="info" title="This report is a draft. The files are marked draft." />}
      <Card className="space-y-3 p-4">
        <div className="grid gap-2 sm:grid-cols-2">
          {([['xlsx', 'Excel workbook'], ['docx', 'Word report'], ['pptx', 'PowerPoint deck'], ['context', 'Planning note']] as const).map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={kinds[key]} onChange={(event) => setKinds((current) => ({ ...current, [key]: event.target.checked }))} />{label}</label>
          ))}
        </div>
        <label className="block text-sm">Deck format<input className={`${controlClass} mt-1 max-w-sm`} value={template} onChange={(event) => setTemplate(event.target.value)} placeholder="Leave empty for the default" /></label>
        <Button size="sm" disabled={!canWrite} onClick={() => onSaved(`/runs/${encodeURIComponent(run.set_id)}/export`, { kinds: Object.entries(kinds).filter(([, on]) => on).map(([key]) => key), template }, 'Files created.')}>Create files</Button>
      </Card>
      <Card className="space-y-2 p-4 text-sm">
        <h3 className="font-semibold">Files for this run</h3>
        {(run.exports ?? []).length === 0 ? <p className="text-[var(--color-gray-500)]">None yet.</p> : null}
        {(run.exports ?? []).map((entry) => (
          <p key={entry.name}><button type="button" className="text-[var(--color-primary-700)] underline" onClick={() => void download(entry)}>{entry.name}</button> <span className="text-[var(--color-gray-500)]">{Math.round(entry.size / 1024)} KB</span></p>
        ))}
      </Card>
      <ul className="list-disc space-y-1 pl-4 text-sm text-[var(--color-gray-700)]">
        <li>Turnaround: {kpis?.turnaround?.hours != null ? `${kpis.turnaround.hours} hours` : 'not finalised yet'}</li>
        <li>Evidence: {kpis?.evidence_traceability?.at_first_run_pct ?? 0}% at first run, {kpis?.evidence_traceability?.now_pct ?? 0}% now</li>
        <li>Validation items resolved: {kpis?.validation_items?.resolved ?? 0}</li>
        <li>Proposals accepted: {kpis?.agent_proposals?.acceptance_rate_pct == null ? 'none decided yet' : `${kpis.agent_proposals.acceptance_rate_pct}%`}</li>
        <li>Audit log: {run.audit?.entries ?? 0} entries, {run.audit?.ok ? 'chain intact' : `problem: ${run.audit?.problem || ''}`}</li>
      </ul>
    </div>
  );
}
