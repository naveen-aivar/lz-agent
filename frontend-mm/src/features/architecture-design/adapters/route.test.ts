import { describe, expect, it } from 'vitest';

import { bindNavigate, followLink, href, navigate } from '@/features/architecture-design/adapters/route';

describe('architecture design routing', () => {
  it('sends a run to the shell as a page parameter and a page as itself', () => {
    const seen: unknown[] = [];
    bindNavigate((page: string, params: Record<string, string>) => seen.push([page, params]));
    navigate('runs', 'abc');
    navigate('new');
    expect(href('runs', 'abc')).toBe('#mm-arch/runs/abc');
    expect(seen).toEqual([
      ['runs', { id: 'abc' }],
      ['new', {}],
    ]);
  });

  it('follows only this agent’s links', () => {
    const seen: string[] = [];
    bindNavigate((page: string) => seen.push(page));
    document.body.innerHTML = '<a id="go" href="#mm-arch/new">New</a><a id="out" href="https://example.com">Out</a>';
    followLink({ target: document.getElementById('go'), preventDefault() {} });
    followLink({ target: document.getElementById('out'), preventDefault() {} });
    expect(seen).toEqual(['new']);
  });
});
