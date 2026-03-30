import { Component } from 'react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          padding: 32,
          textAlign: 'center',
          color: 'var(--text)',
          background: 'var(--bg)',
        }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>⚠️</div>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 8 }}>
            컴포넌트 오류 발생
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16, fontFamily: 'monospace' }}>
            {this.state.error.message}
          </div>
          <button onClick={() => this.setState({ error: null })}>
            다시 시도
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
