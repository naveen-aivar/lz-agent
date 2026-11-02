'use client';

import { Component, type ErrorInfo, type ReactNode } from 'react';

import { Button } from '@/shared/design-system/ui/button';
import { Notice } from '@/shared/components/notice';

/**
 * Keeps a page of an agent that fails to draw from taking the whole dashboard down: the sidebar stays, the person can go to another page or another
 * agent, and this says plainly that the page failed. The reason goes to the console, never to the page.
 */
export class ScreenBoundary extends Component<{ children: ReactNode; resetKey: string }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('A page of the agent failed to draw:', error.message, info.componentStack?.split('\n').slice(0, 3).join(' '));
  }

  componentDidUpdate(previous: { resetKey: string }) {
    if (previous.resetKey !== this.props.resetKey && this.state.failed) this.setState({ failed: false });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <Notice tone="danger" title="This page could not be shown">
        <p>Something went wrong drawing it. Try again, or open another page.</p>
        <Button type="button" variant="secondary" size="sm" className="mt-3" onClick={() => this.setState({ failed: false })}>
          Try again
        </Button>
      </Notice>
    );
  }
}
