/**
 * Memory 面板局部错误边界 — Phase 10
 *
 * Memory 面板渲染异常时只显示局部警告，不影响页面其他部分
 * (DAG、Agent卡片、冲突、预算、融合决策)。
 */
import React from "react";

interface Props {
  children: React.ReactNode;
  runId?: string;
}

interface State {
  hasError: boolean;
}

export default class MemoryPanelErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): Partial<State> {
    return { hasError: true };
  }

  componentDidUpdate(prevProps: Props) {
    // Reset error on runId change so new run gets a fresh render attempt
    if (this.props.runId && prevProps.runId !== this.props.runId) {
      this.setState({ hasError: false });
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            background: "#FFFBEB", borderRadius: 8, padding: 14,
            border: "1px solid #F59E0B", margin: "8px 0", fontSize: 12,
            color: "#92400E",
          }}
        >
          Memory面板渲染异常，不影响本轮协同结果
        </div>
      );
    }
    return this.props.children;
  }
}
