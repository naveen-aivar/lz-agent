'use client';

import { useEffect, useState } from 'react';

import { fileToB64, mraRequest, uploadFile } from '@/features/mra/api';
import type { DeckTemplate, MraInfo } from '@/features/mra/types';
import { Notice } from '@/shared/components/notice';
import { PageHeader } from '@/shared/components/page-header';
import { Badge } from '@/shared/design-system/ui/badge';
import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';
import { useToast } from '@/shared/design-system/ui/toaster';

export function SettingsScreen() {
  const toast = useToast();
  const [info, setInfo] = useState<MraInfo | null>(null);
  const [error, setError] = useState('');
  const [deck, setDeck] = useState<File | null>(null);
  const [doc, setDoc] = useState<File | null>(null);
  const [prefer, setPrefer] = useState(true);

  const load = () => mraRequest<MraInfo>('GET', '/info').then(setInfo).catch((caught) => setError(caught instanceof Error ? caught.message : 'Settings could not be loaded.'));
  useEffect(() => { void load(); }, []);

  const sendTemplate = async (kind: 'pptx' | 'docx', file: File | null) => {
    if (!file) {
      toast({ title: 'Choose a file first.', variant: 'warning' });
      return;
    }
    try {
      let body: Record<string, unknown>;
      try {
        body = { kind, file_name: file.name, upload_id: await uploadFile(file, 'template'), prefer };
      } catch {
        body = { kind, file_name: file.name, file_b64: await fileToB64(file), prefer };
      }
      await mraRequest('POST', '/templates', body);
      toast({ title: `Added ${file.name}.`, variant: 'success' });
      await load();
    } catch (caught) {
      toast({ title: caught instanceof Error ? caught.message : 'The file was not added.', variant: 'danger' });
    }
  };

  const library = info?.templates.pptx;
  return (
    <div className="view-enter space-y-4">
      <PageHeader eyebrow="Readiness" title="Settings" description="The deck format used when a readout is created." />
      {error ? <Notice tone="danger" title="Settings could not be loaded">{error}</Notice> : null}
      {(library?.templates ?? []).map((template) => (
        <TemplateCard key={template.id} template={template} preferred={template.id === library?.preferred} onPrefer={async () => { await mraRequest('POST', `/templates/${template.id}/prefer`, {}); toast({ title: `Now using ${template.name}.`, variant: 'success' }); await load(); }} onRemove={async () => { await mraRequest('POST', `/templates/${template.id}/delete`, {}); toast({ title: `Removed ${template.name}.`, variant: 'success' }); await load(); }} />
      ))}
      <Card className="space-y-3 p-4">
        <h3 className="text-sm font-semibold">Add a deck</h3>
        <input type="file" accept=".pptx" aria-label="Deck file" onChange={(event) => setDeck(event.target.files?.[0] ?? null)} />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={prefer} onChange={(event) => setPrefer(event.target.checked)} />Use it by default from now on</label>
        <Button size="sm" disabled={!deck} onClick={() => void sendTemplate('pptx', deck)}>{deck ? 'Add' : 'Choose a deck first'}</Button>
      </Card>
      <Card className="space-y-3 p-4">
        <h3 className="text-sm font-semibold">Word report template</h3>
        <p className="text-sm text-[var(--color-gray-500)]">{info?.templates.docx ? `Stored: ${info.templates.docx}` : 'None. The report uses the standard readout structure.'}</p>
        <input type="file" accept=".docx" aria-label="Word template" onChange={(event) => setDoc(event.target.files?.[0] ?? null)} />
        <Button size="sm" variant="secondary" disabled={!doc} onClick={() => void sendTemplate('docx', doc)}>{doc ? 'Upload' : 'Choose a document first'}</Button>
      </Card>
      {info ? (
        <Card className="p-4 text-sm">
          <ul className="space-y-1">
            <li>Version {info.version}</li>
            <li>Text engine: {info.engine === 'stub' ? 'offline, no model' : `${info.engine} (${info.model_id})`}</li>
            <li>Data stored in: {info.storage_where}</li>
            <li>Preview: {info.libreoffice ? 'available' : info.hosted ? 'download the file and open it' : 'not available here'}</li>
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

function TemplateCard({ template, preferred, onPrefer, onRemove }: { template: DeckTemplate; preferred: boolean; onPrefer: () => void; onRemove: () => void }) {
  return (
    <Card className="space-y-2 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <strong>{template.name}</strong>
        {template.builtin ? <Badge variant="muted">always available</Badge> : null}
        <Badge variant={preferred ? 'success' : 'muted'}>{preferred ? 'used by default' : 'not the default'}</Badge>
      </div>
      {template.coverage && !template.builtin ? <p>{template.coverage.complete ? `Every part can be filled (${template.coverage.found} of ${template.coverage.expected}).` : template.coverage.warnings.join('; ')}</p> : <p className="text-[var(--color-gray-500)]">{template.description}</p>}
      <div className="flex gap-2">
        {preferred ? null : <Button size="sm" variant="secondary" onClick={onPrefer}>Use this by default</Button>}
        {template.builtin ? null : <Button size="sm" variant="danger" onClick={onRemove}>Remove</Button>}
      </div>
    </Card>
  );
}
