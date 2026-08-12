/**
 * RAG V2 Panel Error Boundary — Phase 11
 *
 * 局部错误隔离：RAG Trace 加载失败不能导致整个页面黑屏。
 */
import React from "react";
import { Alert, Button, Space } from "antd";
import { ReloadOutlined } from "@ant-design/icons";

interface Props {
  children: React.ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: string | null;
}

class RagPanelErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error: error.message || String(error) };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("[RagPanelErrorBoundary]", error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <Alert
          type="warning"
          message={this.props.fallbackTitle || "RAG 面板加载失败"}
          description={
            <Space direction="vertical" style={{ width: "100%" }}>
              <span style={{ color: "#666" }}>
                {this.state.error || "未知错误"}
              </span>
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={this.handleRetry}
              >
                重试
              </Button>
            </Space>
          }
          style={{ margin: 8 }}
        />
      );
    }
    return <>{this.props.children}</>;
  }
}

export default RagPanelErrorBoundary;
