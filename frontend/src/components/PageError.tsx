import { Component, type ReactNode } from "react";

/** If a screen fails to draw, say so and offer a reload, instead of leaving a blank page. */
export class PageError extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("page failed to render", error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="card" role="alert">
        <div className="empty">
          <b>This page could not be shown</b>
          Something went wrong while drawing it. Your data is safe: nothing was changed.
          <div style={{ marginTop: 12 }}><button className="btn primary" onClick={() => window.location.reload()}>Reload</button></div>
        </div>
      </div>
    );
  }
}
