// After `next build` (static export to ./out): list the SHA-256 of every inline <script> in the dashboard's pages, into out/.msp-build.json.
// The CloudFront policy for the dashboard's own pages allows no inline script except these exact ones (infra/render.py reads the list).
import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const out = fileURLToPath(new URL('../out/', import.meta.url));
if (!existsSync(join(out, 'index.html'))) throw new Error('out/index.html is missing: run `next build` first');

const htmlFiles = (dir) =>
  readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? htmlFiles(join(dir, e.name)) : e.name.endsWith('.html') ? [join(dir, e.name)] : []));
const INLINE_SCRIPT = /<script(?![^>]*\ssrc=)[^>]*>([\s\S]*?)<\/script>/g;
const hashes = new Set();
for (const file of htmlFiles(out)) {
  for (const [, body] of readFileSync(file, 'utf8').matchAll(INLINE_SCRIPT)) {
    if (body.trim()) hashes.add(`'sha256-${createHash('sha256').update(body).digest('base64')}'`);
  }
}
writeFileSync(join(out, '.msp-build.json'), JSON.stringify({ id: 'shell', scriptHashes: [...hashes].sort() }, null, 2) + '\n');
console.log(`out/.msp-build.json: ${hashes.size} inline script hash(es)`);
