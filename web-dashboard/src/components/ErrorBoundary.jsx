import React from 'react';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("ErrorBoundary caught an error", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-8 text-center">
          <h1 className="text-2xl font-bold text-red-600 mb-4">Something went wrong</h1>
          <div className="bg-red-50 p-4 rounded-lg border border-red-200 inline-block text-left">
            <p className="font-mono text-sm text-red-800 whitespace-pre-wrap">
              {this.state.error && this.state.error.toString()}
            </p>
          </div>
          <p className="mt-4 text-slate-500">
            Please try refreshing the page.
          </p>
        </div>
      );
    }

    return this.props.children; 
  }
}

export default ErrorBoundary;
