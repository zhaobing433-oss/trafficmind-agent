/**
 * 协作分析错误边界
 * 防止单个 Run 的渲染异常导致整页黑屏
 */
import React from 'react';

interface Props {
  children: React.ReactNode;
  onReset?: () => void;
  onReturnHome?: () => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: string;
}

export default class CollaborationErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: '' };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    this.setState({ errorInfo: errorInfo.componentStack || '' });
    console.error('[CollaborationErrorBoundary]', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      const isDev = typeof window !== 'undefined' && window.location?.hostname === 'localhost';
      return (
        <div style={{
          background: '#FEF2F2', borderRadius: 14, padding: 24,
          border: '2px solid #EF4444', margin: '12px 0',
        }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: '#991B1B', marginBottom: 8 }}>
            协同分析页面渲染失败
          </div>
          <div style={{ fontSize: 12, color: '#DC2626', marginBottom: 12 }}>
            错误信息：{this.state.error?.message || '未知渲染错误'}
          </div>
          {isDev && this.state.error?.stack && (
            <pre style={{
              background: '#FFF', borderRadius: 8, padding: 10, fontSize: 10,
              color: '#991B1B', maxHeight: 160, overflow: 'auto',
              whiteSpace: 'pre-wrap', wordBreak: 'break-all',
            }}>
              {this.state.error.stack}
            </pre>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button onClick={() => {
              this.setState({ hasError: false, error: null, errorInfo: '' });
              this.props.onReset?.();
            }} style={{
              padding: '6px 14px', borderRadius: 8, border: '1px solid #EF4444',
              background: '#FFF', color: '#EF4444', cursor: 'pointer', fontSize: 12, fontWeight: 600,
            }}>
              重新加载本轮详情
            </button>
            <button onClick={() => this.props.onReturnHome?.()} style={{
              padding: '6px 14px', borderRadius: 8, border: 'none',
              background: '#0F766E', color: '#FFF', cursor: 'pointer', fontSize: 12, fontWeight: 600,
            }}>
              返回协同分析首页
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
