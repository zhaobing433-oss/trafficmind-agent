/**
 * LayoutShell — 左侧 Sidebar + 右侧内容区
 */
import { ReactNode, useState } from 'react';
import Sidebar from './Sidebar';

interface RecentItem { id: string; title: string; mode: string; updatedAt: number }

interface Props {
  children: ReactNode;
  activeView: string;
  onNavigate: (view: string) => void;
  onRecentClick: (id: string, mode: string) => void;
  onNewConversation: () => void;
  activeConvId?: string;
  recentList: RecentItem[];
}

export default function LayoutShell({ children, activeView, onNavigate, onRecentClick, onNewConversation, activeConvId, recentList }: Props) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: '#F7F8FA' }}>
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        onNavigate={onNavigate}
        onRecentClick={onRecentClick}
        onNewConversation={onNewConversation}
        activeView={activeView}
        activeConvId={activeConvId}
        recentList={recentList}
      />
      <div style={{
        flex: 1, marginLeft: collapsed ? 72 : 240,
        transition: 'margin-left 0.2s ease',
        display: 'flex', flexDirection: 'column', minHeight: '100vh',
      }}>
        {children}
      </div>
    </div>
  );
}
