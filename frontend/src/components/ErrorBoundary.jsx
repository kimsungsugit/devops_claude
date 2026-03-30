import React from "react";

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo });
    console.error("[ErrorBoundary]", error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      const { fallback, name } = this.props;
      if (fallback) return fallback(this.state.error, this.handleReset);
      return (
        <div style={{
          padding: "2rem",
          margin: "1rem",
          borderRadius: "8px",
          backgroundColor: "var(--error-bg, #fef2f2)",
          border: "1px solid var(--error-border, #fca5a5)",
          color: "var(--error-text, #991b1b)",
        }}>
          <h3 style={{ margin: "0 0 0.5rem" }}>
            {name ? `${name} 렌더링 오류` : "렌더링 오류가 발생했습니다"}
          </h3>
          <p style={{ margin: "0 0 1rem", fontSize: "0.9rem", opacity: 0.8 }}>
            {this.state.error?.message || "알 수 없는 오류"}
          </p>
          <button
            onClick={this.handleReset}
            style={{
              padding: "0.5rem 1rem",
              borderRadius: "4px",
              border: "1px solid currentColor",
              background: "transparent",
              color: "inherit",
              cursor: "pointer",
              fontSize: "0.9rem",
            }}
          >
            다시 시도
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
