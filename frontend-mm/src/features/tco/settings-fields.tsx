'use client';

import type { Dispatch, SetStateAction } from 'react';
import { SETTING_GROUPS, type SettingValues } from '@/features/tco/parameters';

const INPUT = 'mt-1 w-full rounded-[var(--radius-md)] border border-[var(--color-gray-200)] px-3 py-2 text-sm';

/** The optional settings of a new assessment, in groups. */
export function SettingsFields({ values, setValues }: { values: SettingValues; setValues: Dispatch<SetStateAction<SettingValues>> }) {
  const set = (key: string, value: string | boolean) => setValues((current) => ({ ...current, [key]: value }));
  return (
    <details>
      <summary className="cursor-pointer text-sm font-medium">Optional settings (otherwise you confirm them later)</summary>
      <div className="disclosure-body mt-3 grid gap-5">
        <p className="text-sm text-[var(--color-gray-500)]">Fill in what you already know. AWS Transform’s questions are answered from these settings; anything they do not cover is still asked.</p>
        {SETTING_GROUPS.map((group) => (
          <fieldset key={group.title} className="grid gap-3">
            <legend className="text-sm font-medium">{group.title}</legend>
            {group.hint ? <p className="text-sm text-[var(--color-gray-500)]">{group.hint}</p> : null}
            <div className="grid gap-3 sm:grid-cols-2">
              {group.fields.map((field) => {
                const id = `setting-${field.key}`;
                if (field.kind === 'checkbox') {
                  return (
                    <label key={field.key} className="flex items-center gap-2 text-sm sm:col-span-2">
                      <input id={id} type="checkbox" checked={values[field.key] === true} onChange={(event) => set(field.key, event.target.checked)} /> {field.label}
                    </label>
                  );
                }
                return (
                  <div key={field.key}>
                    <label htmlFor={id} className="text-sm">{field.label}</label>
                    {field.kind === 'select' ? (
                      <select id={id} className={INPUT} value={String(values[field.key] ?? '')} onChange={(event) => set(field.key, event.target.value)}>
                        {(field.choices ?? []).map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
                      </select>
                    ) : (
                      <input
                        id={id}
                        className={INPUT}
                        type={field.kind === 'number' ? 'number' : 'text'}
                        min={field.min}
                        max={field.max}
                        step={field.kind === 'number' ? 'any' : undefined}
                        placeholder={field.placeholder}
                        list={field.suggestions ? `${id}-list` : undefined}
                        value={String(values[field.key] ?? '')}
                        onChange={(event) => set(field.key, event.target.value)}
                      />
                    )}
                    {field.suggestions ? <datalist id={`${id}-list`}>{field.suggestions.map((option) => <option key={option} value={option} />)}</datalist> : null}
                  </div>
                );
              })}
            </div>
          </fieldset>
        ))}
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={values.auto_answer !== false} onChange={(event) => set('auto_answer', event.target.checked)} />
          Answer AWS Transform automatically when these settings cover everything it asks
        </label>
      </div>
    </details>
  );
}
