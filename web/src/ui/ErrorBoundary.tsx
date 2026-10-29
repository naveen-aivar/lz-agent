import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
/** A page that throws shows what failed, not a blank screen. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error(error, info.componentStack); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="notice notice-err" role="alert">
        <strong>This page could not be shown.</strong> {this.state.error.message}
        <br /><button type="button" className="btn btn-sm" onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    );
  }
}
