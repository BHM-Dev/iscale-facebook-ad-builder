import React from 'react';

// Catches a page that fails to render or load (e.g. its lazy chunk 404s after a deploy and
// lib/lazyPage.js has already used its one reload) so the sidebar stays up instead of a blank app.
// Layout keys it by path, so navigating to another page clears the error.
export default class PageErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error) {
    console.error('Page failed to load:', error);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="p-8">
        <p className="text-sm text-gray-700">This page didn't load.</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-3 rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700"
        >
          Reload
        </button>
      </div>
    );
  }
}
