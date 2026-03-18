"use client";

import { Component, type ReactNode } from "react";
import { Button } from "./Button";

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-xl border border-bah-red/20 bg-bah-red/5 p-6 text-center">
          <div className="text-2xl mb-2">⚠️</div>
          <div className="text-sm text-bah-red font-semibold mb-1">
            {this.props.fallbackTitle ?? "Something went wrong"}
          </div>
          <div className="text-xs text-bah-muted mb-4 font-mono">
            {this.state.error?.message}
          </div>
          <Button
            variant="outline"
            color="#ef4444"
            onClick={() => this.setState({ hasError: false, error: null })}
          >
            Retry
          </Button>
        </div>
      );
    }

    return this.props.children;
  }
}
