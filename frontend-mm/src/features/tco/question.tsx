'use client';

import { useState } from 'react';

import { buildAnswer, hasNoteField, type PendingInput } from '@/features/tco/answer';
import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';

/** The question the assessment is waiting on. Choices are radios, so the list never covers the question. */
export function QuestionForm({ pending, onSubmit }: { pending: PendingInput; onSubmit: (answer: Record<string, unknown>) => Promise<void> }) {
  const [values, setValues] = useState<Record<string, unknown>>(() => Object.fromEntries(pending.fields.map((field) => [field.key, field.default ?? (field.type === 'boolean' ? false : '')])));
  const [note, setNote] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');

  return (
    <Card className="view-enter mb-4 p-5">
      <form
        noValidate
        aria-labelledby="q-title"
        onSubmit={(event) => {
          event.preventDefault();
          const result = buildAnswer(pending, values, note);
          if ('errors' in result) {
            setErrors(result.errors);
            return;
          }
          setSending(true);
          setSendError('');
          void onSubmit(result.answer)
            .catch((error: unknown) => setSendError(error instanceof Error ? error.message : 'The answer could not be sent.'))
            .finally(() => setSending(false));
        }}
      >
        <h2 id="q-title" className="text-lg font-semibold">
          {pending.kind === 'scenario_confirmation' ? 'Confirm the settings' : 'The assessment has a question'}
        </h2>
        <p className="mt-1 text-sm text-[var(--color-gray-700)]">{pending.message}</p>
        <div className="mt-4 grid gap-4">
          {pending.fields.map((field) => {
            const id = `q-${field.key}`;
            const error = errors[field.key];
            return (
              <div key={field.key}>
                <label htmlFor={field.type === 'enum' ? undefined : id} className="text-sm font-medium">
                  {field.label}
                  {field.required ? <span className="text-[var(--color-gray-500)]"> (required)</span> : null}
                </label>
                {field.type === 'enum' ? (
                  <div role="radiogroup" aria-label={field.label} className="mt-2 grid gap-2">
                    {(field.options ?? []).map((option) => (
                      <label key={option} className="flex items-center gap-2 text-sm">
                        <input type="radio" name={field.key} value={option} checked={values[field.key] === option} onChange={() => setValues((current) => ({ ...current, [field.key]: option }))} />
                        {option}
                      </label>
                    ))}
                  </div>
                ) : field.type === 'boolean' ? (
                  <input id={id} className="mt-2" type="checkbox" checked={values[field.key] === true} onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.checked }))} />
                ) : (
                  <input
                    id={id}
                    className="mt-2 w-full rounded-[var(--radius-md)] border border-[var(--color-gray-200)] px-3 py-2 text-sm"
                    type={field.type === 'number' ? 'number' : 'text'}
                    value={String(values[field.key] ?? '')}
                    aria-invalid={error ? true : undefined}
                    onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
                  />
                )}
                {error ? <p className="mt-1 text-sm text-[var(--color-danger-700)]" role="alert">{error}</p> : null}
              </div>
            );
          })}
          {pending.allow_free_text && !hasNoteField(pending) ? (
            <div>
              <label htmlFor="q-note" className="text-sm font-medium">Note (optional)</label>
              <textarea id="q-note" className="mt-2 w-full rounded-[var(--radius-md)] border border-[var(--color-gray-200)] px-3 py-2 text-sm" rows={3} maxLength={1000} value={note} onChange={(event) => setNote(event.target.value)} />
            </div>
          ) : null}
        </div>
        {sendError ? <p className="mt-3 text-sm text-[var(--color-danger-700)]" role="alert">{sendError}</p> : null}
        <div className="mt-4">
          <Button type="submit" loading={sending}>Submit answer</Button>
        </div>
      </form>
    </Card>
  );
}
