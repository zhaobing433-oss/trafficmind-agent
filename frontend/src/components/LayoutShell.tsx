/**
 * LayoutShell — 左侧 Sidebar + 右侧内容区
 */
import { ReactNode, useState } from 'react';
import Sidebar from './Sidebar';
import { visualTokens } from '../styles/visualTokens';

interface RecentItem { id: string; title: string; mode: string; updatedAt: number }

interface Props {
  children: ReactNode;
  activeView: string;
  onNavigate: (view: string) => void;
  onRecentClick: (id: string) => void;
  onNewConversation: () => void;
  onRenameSession: (id: string, newTitle: string) => void;
  onDeleteSession: (id: string) => void;
  activeConvId?: string;
  recentList: RecentItem[];
}

export default function LayoutShell({ children, activeView, onNavigate, onRecentClick, onNewConversation, onRenameSession, onDeleteSession, activeConvId, recentList }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const sidebarWidth = collapsed ? 72 : 248;

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: visualTokens.color.appBg, color: visualTokens.color.text }}>
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        onNavigate={onNavigate}
        onRecentClick={onRecentClick}
        onNewConversation={onNewConversation}
        onRenameSession={onRenameSession}
        onDeleteSession={onDeleteSession}
        activeView={activeView}
        activeConvId={activeConvId}
        recentList={recentList}
      />
      <div style={{
        flex: 1, marginLeft: sidebarWidth,
        transition: 'margin-left 0.2s ease',
        display: 'flex', flexDirection: 'column', minHeight: '100vh', minWidth: 0,
      }}>
        {children}
      </div>
    </div>
  );
}
