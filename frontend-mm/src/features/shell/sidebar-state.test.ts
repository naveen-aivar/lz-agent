import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSidebarCollapsed } from '@/features/shell/sidebar-state';

function windowWidth(narrow: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: narrow, media: query, addEventListener: () => {}, removeEventListener: () => {} }));
}

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe('useSidebarCollapsed', () => {
  it('shows icons only by default in a narrow window and the full sidebar in a wide one', () => {
    windowWidth(true);
    expect(renderHook(() => useSidebarCollapsed()).result.current[0]).toBe(true);
    windowWidth(false);
    expect(renderHook(() => useSidebarCollapsed()).result.current[0]).toBe(false);
  });

  it('keeps what the person chose, whatever the window is', () => {
    windowWidth(true);
    const { result } = renderHook(() => useSidebarCollapsed());
    act(() => result.current[1](false));
    expect(result.current[0]).toBe(false);
    expect(window.localStorage.getItem('mm.sidebar.collapsed')).toBe('false');
    windowWidth(false);
    act(() => result.current[1](true));
    expect(result.current[0]).toBe(true);
  });
});
