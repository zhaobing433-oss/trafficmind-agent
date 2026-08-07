/** Workflow V1 错误边界 */
import React, { Component, ErrorInfo, ReactNode } from 'react';
import { Alert, Button } from 'antd';

interface Props { children: ReactNode; runId?: string; }
interface State { hasError: boolean; error: Error | null; }

export class WorkflowErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[WorkflowErrorBoundary]', error, info.componentStack?.slice(0, 500));
  }

  render() {
    if (this.state.hasError) {
      return (
        <Alert
          type="error"
          message="Workflow 组件渲染错误"
          description={this.state.error?.message || '未知错误'}
          action={
            <Button size="small" onClick={() => this.setState({ hasError: false, error: null })}>
              重试
            </Button>
          }
        />
      );
    }
    return this.props.children;
  }
}
