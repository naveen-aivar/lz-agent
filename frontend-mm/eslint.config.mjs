import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { FlatCompat } from '@eslint/eslintrc';

const __dirname = dirname(fileURLToPath(import.meta.url));
const compat = new FlatCompat({ baseDirectory: __dirname });

/** @type {import('eslint').Linter.Config[]} */
const config = [
  // agents/ holds the build scripts and patches of the embedded agents (not this app's source); .build/ is generated.
  // public/agents/*/pdfjs/ is pdf.js's own minified vendor build, copied in as-is: not this app's source either.
  { ignores: ['.next/**', 'node_modules/**', 'out/**', '.build/**', 'agents/**', 'infra/**', 'next-env.d.ts', 'public/agents/*/pdfjs/**'] },
  ...compat.extends('next/core-web-vitals', 'next/typescript'),
];

export default config;
