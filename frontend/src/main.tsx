import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import { visualTokens } from './styles/visualTokens';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: visualTokens.color.primary,
          colorSuccess: '#10B981',
          colorWarning: '#F59E0B',
          colorError: '#EF4444',
          colorBgBase: visualTokens.color.appBg,
          colorBgContainer: visualTokens.color.surface,
          colorBgLayout: visualTokens.color.appBg,
          colorText: visualTokens.color.text,
          colorTextSecondary: visualTokens.color.textMuted,
          colorBorder: visualTokens.color.border,
          borderRadius: visualTokens.radius.md,
          borderRadiusLG: visualTokens.radius.md,
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>
);
