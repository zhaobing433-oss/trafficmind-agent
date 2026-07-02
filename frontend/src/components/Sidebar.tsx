/**
 * Sidebar — 左侧导航 + 可滚动最近分析（时间分组）
 */
import { MenuFoldOutlined, MenuUnfoldOutlined, PlusOutlined } from '@ant-design/icons';
import { Tag } from 'antd';

const NAV_ITEMS = [
  { key: 'home', label: '首页对话', icon: '💬' },
  { key: 'analyze', label: '事件研判', icon: '🔍' },
  { key: 'qa', label: '知识问答', icon: '📖' },
  { key: 'similar', label: '相似案例', icon: '📊' },
  { key: 'multi', label: '协同分析', icon: '🤝' },
  { key: 'report', label: '统计报告', icon: '📋' },
  { key: 'alert', label: '风险提醒', icon: '⚠' },
  { key: 'guide', label: '文档指南', icon: '📘' },
];

const MODE_LABELS: Record<string, string> = { react: '诊断', routed: '研判', rag: '问答', hybrid: '相似', report: '报告' };

interface RecentItem { id: string; title: string; mode: string; updatedAt: number }

function groupByTime(items: RecentItem[]): { label: string; items: RecentItem[] }[] {
  const now = Date.now();
  const today = new Date().setHours(0, 0, 0, 0);
  const weekAgo = today - 7 * 86400000;

  const todayItems: RecentItem[] = [];
  const weekItems: RecentItem[] = [];
  const olderItems: RecentItem[] = [];

  items.forEach(item => {
    if (item.updatedAt >= today) todayItems.push(item);
    else if (item.updatedAt >= weekAgo) weekItems.push(item);
    else olderItems.push(item);
  });

  const groups: { label: string; items: RecentItem[] }[] = [];
  if (todayItems.length) groups.push({ label: '今天', items: todayItems });
  if (weekItems.length) groups.push({ label: '近 7 天', items: weekItems });
  if (olderItems.length) groups.push({ label: '更早', items: olderItems });
  return groups;
}

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  onNavigate: (view: string) => void;
  onRecentClick: (id: string, mode: string) => void;
  onNewConversation: () => void;
  activeView: string;
  activeConvId?: string;
  recentList: RecentItem[];
}

export default function Sidebar({
  collapsed, onToggle, onNavigate, onRecentClick, onNewConversation,
  activeView, activeConvId, recentList,
}: Props) {
  const groups = groupByTime(recentList);

  return (
    <div style={{
      position: 'fixed', left: 0, top: 0, bottom: 0,
      width: collapsed ? 72 : 240, background: '#FFFFFF',
      borderRight: '1px solid #E5E7EB',
      display: 'flex', flexDirection: 'column',
      transition: 'width 0.2s ease', zIndex: 100, overflow: 'hidden',
    }}>
      {/* Logo */}
      <div style={{ padding: collapsed ? '16px 12px' : '20px 20px 16px', borderBottom: '1px solid #F3F4F6' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: 'linear-gradient(135deg, #0F766E, #14B8A6)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#FFF', fontWeight: 700, fontSize: 14, flexShrink: 0 }}>T</div>
          {!collapsed && (
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#111827', lineHeight: 1.2 }}>TrafficMind</div>
              <div style={{ fontSize: 11, color: '#9CA3AF' }}>Phase 4</div>
            </div>
          )}
        </div>
      </div>

      {/* New conversation button */}
      {!collapsed && (
        <div style={{ padding: '8px 12px' }}>
          <button onClick={onNewConversation} style={{
            width: '100%', border: '1px solid #E5E7EB', borderRadius: 10, padding: '8px 0',
            background: '#FFF', cursor: 'pointer', fontSize: 13, color: '#0F766E',
            fontWeight: 500, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
          }}>
            <PlusOutlined /> 新对话
          </button>
        </div>
      )}

      {/* Nav */}
      <nav style={{ padding: '4px 8px', flexShrink: 0 }}>
        {NAV_ITEMS.map(item => (
          <div key={item.key} onClick={() => onNavigate(item.key)}
            style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: collapsed ? '10px 16px' : '10px 14px',
              marginBottom: 2, borderRadius: 8, cursor: 'pointer', fontSize: 13,
              color: activeView === item.key ? '#0F766E' : '#4B5563',
              background: activeView === item.key ? '#F0FDFA' : 'transparent',
              fontWeight: activeView === item.key ? 600 : 400,
              transition: 'all 0.15s', whiteSpace: 'nowrap',
            }}>
            <span style={{ fontSize: 16, flexShrink: 0 }}>{item.icon}</span>
            {!collapsed && item.label}
          </div>
        ))}
      </nav>

      {/* Recent — scrollable */}
      {!collapsed && (
        <div style={{
          flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column',
          borderTop: '1px solid #F3F4F6', minHeight: 0,
        }}>
          <div style={{ padding: '10px 16px 4px', fontSize: 11, color: '#9CA3AF', fontWeight: 600, flexShrink: 0 }}>
            最近分析
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '0 12px 8px', maxHeight: 280 }}>
            {recentList.length === 0 ? (
              <div style={{ color: '#D1D5DB', fontSize: 11, padding: '8px 4px' }}>暂无记录</div>
            ) : groups.map(group => (
              <div key={group.label} style={{ marginBottom: 6 }}>
                <div style={{ fontSize: 10, color: '#D1D5DB', padding: '2px 4px' }}>{group.label}</div>
                {group.items.map(s => (
                  <div key={s.id}
                    onClick={() => onRecentClick(s.id, s.mode)}
                    style={{
                      padding: '6px 8px', borderRadius: 8, cursor: 'pointer',
                      background: activeConvId === s.id ? '#F0FDFA' : 'transparent',
                      border: activeConvId === s.id ? '1px solid #0F766E20' : '1px solid transparent',
                      marginBottom: 1,
                    }}>
                    <div style={{ fontSize: 12, color: activeConvId === s.id ? '#0F766E' : '#374151', fontWeight: activeConvId === s.id ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {s.title}
                    </div>
                    <div style={{ fontSize: 10, color: '#9CA3AF', marginTop: 1 }}>
                      <Tag style={{ fontSize: 9, lineHeight: '14px', padding: '0 4px' }}>{MODE_LABELS[s.mode] || s.mode}</Tag>
                      {new Date(s.updatedAt).toLocaleDateString()}
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Toggle */}
      <div onClick={onToggle} style={{ padding: '10px', textAlign: 'center', cursor: 'pointer', borderTop: '1px solid #F3F4F6', color: '#9CA3AF', fontSize: 16 }}>
        {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
      </div>
    </div>
  );
}
