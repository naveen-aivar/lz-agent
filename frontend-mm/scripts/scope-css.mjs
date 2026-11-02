#!/usr/bin/env node
// Makes a plain stylesheet safe to live in the dashboard beside the other agents' styles: every rule is put under one class, so what an agent
// styles ("button", ".card", "h1") applies only inside that agent's own root element, never to the sidebar or to another agent.
//
//   node scripts/scope-css.mjs <scopeClass> <in.css> [<out.css>]      (out defaults to stdout)
//
// What it does (postcss + native CSS nesting, which every browser the dashboard supports has):
//   - every rule becomes `& <selector>` inside `.scopeClass { ... }`;  :root, html and body become the scope root itself (so the CSS variables an
//     agent declares on :root apply to its root element);  * becomes `& *`
//   - @media, @supports and @container blocks are nested inside the scope, their rules rewritten the same way
//   - @keyframes, @font-face, @property, @import, @charset and @layer statements stay at the top, and each @keyframes name is prefixed with the scope
//     (and the animation / animation-name declarations that use it follow), so two agents' "fade-in" cannot collide
// What it cannot do: style something React puts OUTSIDE the agent's root element (a dialog or menu rendered into document.body). Give such a
// portal the scope class as well (see PORTING.md).
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

import postcss from 'postcss';

const HOISTED = new Set(['charset', 'import', 'font-face', 'keyframes', '-webkit-keyframes', 'property', 'layer', 'namespace', 'page', 'counter-style']);
const ROOT_TOKEN = /^(:root|html|body)(?![\w-])/;

/** Splits a selector list at its top-level commas (not the ones inside :is(), :not() and the like). */
function splitSelectors(list) {
  const parts = [];
  let depth = 0;
  let current = '';
  for (const char of list) {
    if (char === '(' || char === '[') depth += 1;
    if (char === ')' || char === ']') depth -= 1;
    if (char === ',' && depth === 0) {
      parts.push(current);
      current = '';
    } else current += char;
  }
  if (current.trim()) parts.push(current);
  return parts.map((part) => part.trim()).filter(Boolean);
}

export function scopeSelector(selector) {
  return splitSelectors(selector)
    .map((part) => {
      if (part.startsWith('&')) return part;
      if (ROOT_TOKEN.test(part)) return part.replace(ROOT_TOKEN, '&');
      if (part === '*' || part.startsWith('*,')) return '& *';
      return `& ${part}`;
    })
    .join(', ');
}

function rewriteIn(container) {
  container.walkRules((rule) => {
    if (rule.parent && rule.parent.type === 'atrule' && /^(keyframes|-webkit-keyframes)$/i.test(rule.parent.name)) return;
    rule.selector = scopeSelector(rule.selector);
  });
}

export function scopeCss(css, scope) {
  const root = postcss.parse(css);
  const names = new Map();
  root.walkAtRules(/^(-webkit-)?keyframes$/i, (atrule) => names.set(atrule.params.trim(), `${scope}-${atrule.params.trim()}`));

  const top = postcss.root();
  const wrapper = postcss.rule({ selector: `.${scope}` });
  root.each((node) => {
    if (node.type === 'comment') return;
    if (node.type === 'atrule' && HOISTED.has(node.name.toLowerCase())) {
      const copy = node.clone();
      if (/^(-webkit-)?keyframes$/i.test(copy.name)) copy.params = names.get(copy.params.trim());
      top.append(copy);
      return;
    }
    const copy = node.clone();
    if (copy.type === 'rule') copy.selector = scopeSelector(copy.selector);
    else if (copy.type === 'atrule') rewriteIn(copy);
    wrapper.append(copy);
  });
  wrapper.walkDecls(/^(-webkit-)?animation(-name)?$/i, (decl) => {
    decl.value = decl.value
      .split(/(\s+|,)/)
      .map((token) => names.get(token) ?? token)
      .join('');
  });
  top.append(wrapper);
  return top.toString();
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [, , scope, input, output] = process.argv;
  if (!scope || !input) {
    console.error('usage: node scripts/scope-css.mjs <scopeClass> <in.css> [<out.css>]');
    process.exit(2);
  }
  const result = scopeCss(readFileSync(input, 'utf8'), scope);
  if (output) writeFileSync(output, result);
  else process.stdout.write(result);
}
