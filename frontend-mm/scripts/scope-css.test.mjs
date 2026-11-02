import assert from 'node:assert/strict';
import test from 'node:test';

import { scopeCss, scopeSelector } from './scope-css.mjs';

test('every rule goes under the scope, :root/html/body become the scope itself, * becomes & *', () => {
  const out = scopeCss(':root{--a:1} body{margin:0} * {box-sizing:border-box} .card{color:red} button:hover,.x > a{color:blue}', 'msp-x');
  assert.match(out, /^\.msp-x\s*\{/m);
  assert.match(out, /&\s*\{\s*--a:1/);
  assert.match(out, /&\s*\{\s*margin:0/);
  assert.match(out, /& \*\s*\{/);
  assert.match(out, /& \.card\s*\{/);
  assert.match(out, /& button:hover, & \.x > a\s*\{/);
});

test('media and supports blocks stay inside the scope with their rules rewritten', () => {
  const out = scopeCss('@media (max-width: 800px){ .a{display:none} } @supports (display:grid){ .b{display:grid} }', 'msp-x');
  assert.match(out, /@media \(max-width: 800px\)\s*\{\s*& \.a/);
  assert.match(out, /@supports \(display:grid\)\s*\{\s*& \.b/);
});

test('keyframes, font-face, property and import stay at the top; keyframe names get the scope and their users follow', () => {
  const out = scopeCss('@import url(x.css); @font-face{font-family:F;src:url(f.woff2)} @keyframes spin{to{transform:rotate(1turn)}} .a{animation:spin 1s linear infinite} .b{animation-name:spin}', 'msp-x');
  assert.ok(out.indexOf('@keyframes msp-x-spin') < out.indexOf('.msp-x {') || out.indexOf('@keyframes msp-x-spin') < out.indexOf('.msp-x{'));
  assert.match(out, /@import url\(x\.css\)/);
  assert.match(out, /@font-face/);
  assert.match(out, /animation:msp-x-spin 1s linear infinite/);
  assert.match(out, /animation-name:msp-x-spin/);
  assert.doesNotMatch(out, /@keyframes spin/);
});

test('a selector already written with & is left alone, and commas inside :is() do not split it', () => {
  assert.equal(scopeSelector('&.on'), '&.on');
  assert.equal(scopeSelector(':is(.a, .b) c'), '& :is(.a, .b) c');
});
