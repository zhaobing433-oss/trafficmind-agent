/**
 * Sidebar — Phase 7: 新对话置顶 + 最近分析大占比 + 工作区折叠紧凑
 */
import { useState } from 'react';
import { MenuFoldOutlined, MenuUnfoldOutlined, PlusOutlined, EditOutlined, DeleteOutlined, DownOutlined, RightOutlined } from '@ant-design/icons';
import { Tag, Input, Modal } from 'antd';

const NAV_ITEMS = [
  { key: 'multi', label: '协同分析', icon: '🤝' },
  { key: 'workflow', label: '工作流', icon: '🔀' },
  { key: 'qa', label: '知识库', icon: '📖' },
  { key: 'report', label: '统计报告', icon: '📋' },
  { key: 'alert', label: '风险提醒', icon: '⚠' },
];

const MODE_LABELS: Record<string, string> = { react: '诊断', routed: '研判', rag: '知识库', hybrid: '相似', report: '报告', collaboration: '协同' };

interface RecentItem { id: string; title: string; mode: string; updatedAt: number }

function groupByTime(items: RecentItem[]): { label: string; items: RecentItem[] }[] {
  const today = new Date().setHours(0, 0, 0, 0);
  const weekAgo = today - 7 * 86400000;
  const todayItems: RecentItem[] = []; const weekItems: RecentItem[] = []; const olderItems: RecentItem[] = [];
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
  collapsed: boolean; onToggle: () => void;
  onNavigate: (view: string) => void; onRecentClick: (id: string) => void;
  onNewConversation: () => void; onRenameSession: (id: string, newTitle: string) => void;
  onDeleteSession: (id: string) => void;
  activeView: string; activeConvId?: string; recentList: RecentItem[];
}

export default function Sidebar({ collapsed, onToggle, onNavigate, onRecentClick, onNewConversation, onRenameSession, onDeleteSession, activeView, activeConvId, recentList }: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [workspaceOpen, setWorkspaceOpen] = useState(true);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const groups = groupByTime(recentList);

  const startRename = (e: React.MouseEvent, item: RecentItem) => { e.stopPropagation(); setEditingId(item.id); setEditTitle(item.title); };
  const confirmRename = (id: string) => { if (editTitle.trim()) onRenameSession(id, editTitle.trim()); setEditingId(null); };

  const handleDelete = (e: React.MouseEvent, item: RecentItem) => {
    e.stopPropagation();
    Modal.confirm({
      title: '删除分析记录',
      content: '删除后该分析记录及所有历史轮次都会永久删除，是否继续？',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      centered: true,
      onOk: () => onDeleteSession(item.id),
    });
  };

  return (
    <div style={{ position: 'fixed', left: 0, top: 0, bottom: 0, width: collapsed ? 72 : 240, background: '#FFFFFF', borderRight: '1px solid #E5E7EB', display: 'flex', flexDirection: 'column', transition: 'width 0.2s ease', zIndex: 100, overflow: 'hidden' }}>
      {/* Logo */}
      <div style={{ padding: collapsed ? '12px 12px' : '16px 16px 12px', borderBottom: '1px solid #F3F4F6', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 28, height: 28, borderRadius: 7, background: 'linear-gradient(135deg, #0F766E, #14B8A6)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#FFF', fontWeight: 700, fontSize: 13, flexShrink: 0 }}>T</div>
          {!collapsed && <div><div style={{ fontSize: 14, fontWeight: 700, color: '#111827', lineHeight: 1.2 }}>TrafficMind</div></div>}
        </div>
      </div>

      {/* New conversation */}
      {!collapsed && (
        <div style={{ padding: '6px 12px', flexShrink: 0 }}>
          <button onClick={onNewConversation} style={{ width: '100%', border: '1px solid #E5E7EB', borderRadius: 10, padding: '7px 0', background: '#FFF', cursor: 'pointer', fontSize: 12, color: '#0F766E', fontWeight: 500, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
            <PlusOutlined /> 新对话
          </button>
        </div>
      )}

      {/* Recent sessions — MAIN SPACE */}
      {!collapsed && (
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div style={{ padding: '6px 16px 2px', fontSize: 10, color: '#9CA3AF', fontWeight: 600, flexShrink: 0 }}>最近分析</div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '0 12px 4px' }}>
            {recentList.length === 0 ? <div style={{ color: '#D1D5DB', fontSize: 11, padding: '4px' }}>暂无记录</div> : groups.map(group => (
              <div key={group.label} style={{ marginBottom: 2 }}>
                <div style={{ fontSize: 10, color: '#D1D5DB', padding: '1px 4px' }}>{group.label}</div>
                {group.items.map(s => (
                  <div key={s.id}
                    onClick={() => onRecentClick(s.id)}
                    onMouseEnter={() => setHoveredId(s.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    style={{ padding: '5px 6px', borderRadius: 7, cursor: 'pointer', background: activeConvId === s.id ? '#F0FDFA' : 'transparent', border: activeConvId === s.id ? '1px solid #0F766E20' : '1px solid transparent', marginBottom: 1, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 4 }}>
                      {editingId === s.id ? (
                        <Input size="small" value={editTitle} onChange={e => setEditTitle(e.target.value)} onPressEnter={() => confirmRename(s.id)} onBlur={() => confirmRename(s.id)} onClick={e => e.stopPropagation()} style={{ fontSize: 11 }} autoFocus />
                      ) : (
                        <>
                          <div style={{ fontSize: 11, color: activeConvId === s.id ? '#0F766E' : '#374151', fontWeight: activeConvId === s.id ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{s.title || '未命名交通分析'}</div>
                          {MODE_LABELS[s.mode] && (
                            <Tag style={{ fontSize: 9, lineHeight: '14px', padding: '0 4px', margin: 0, border: 'none', background: '#F3F4F6', color: '#6B7280', borderRadius: 4, flexShrink: 0 }}>
                              {MODE_LABELS[s.mode]}
                            </Tag>
                          )}
                        </>
                      )}
                    </div>
                    {!editingId && (
                      <span style={{ display: 'flex', gap: 2, flexShrink: 0 }}>
                        {hoveredId === s.id && (
                          <span onClick={(e) => handleDelete(e, s)} style={{ color: '#EF4444', cursor: 'pointer', fontSize: 11, padding: 2 }} title="删除">
                            <DeleteOutlined />
                          </span>
                        )}
                        <span onClick={(e) => startRename(e as React.MouseEvent, s)} style={{ color: '#D1D5DB', cursor: 'pointer', fontSize: 11, padding: 2 }} title="重命名">
                          <EditOutlined />
                        </span>
                      </span>
                    )}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Workspace nav — compact, collapsible */}
      {!collapsed && (
        <div style={{ flexShrink: 0, borderTop: '1px solid #F3F4F6' }}>
          <div onClick={() => setWorkspaceOpen(!workspaceOpen)} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 16px', cursor: 'pointer', fontSize: 10, color: '#9CA3AF', fontWeight: 600 }}>
            工作区 {workspaceOpen ? <DownOutlined style={{ fontSize: 8 }} /> : <RightOutlined style={{ fontSize: 8 }} />}
          </div>
          {workspaceOpen && (
            <div style={{ padding: '2px 8px 6px' }}>
              {NAV_ITEMS.map(item => (
                <div key={item.key} onClick={() => onNavigate(item.key)}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 8px', borderRadius: 6, cursor: 'pointer', fontSize: 12, color: activeView === item.key ? '#0F766E' : '#4B5563', background: activeView === item.key ? '#F0FDFA' : 'transparent', fontWeight: activeView === item.key ? 600 : 400, marginBottom: 1 }}>
                  <span style={{ fontSize: 14 }}>{item.icon}</span> {item.label}
                </div>
              ))}
            </div>
          )}
          {/* Guide link at bottom */}
          <div onClick={() => onNavigate('guide')} style={{ padding: '4px 16px', cursor: 'pointer', fontSize: 10, color: '#D1D5DB' }}>文档指南</div>
        </div>
      )}

      {/* Toggle */}
      <div onClick={onToggle} style={{ padding: '6px', textAlign: 'center', cursor: 'pointer', borderTop: '1px solid #F3F4F6', color: '#9CA3AF', fontSize: 14, flexShrink: 0 }}>
        {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
      </div>
    </div>
  );
}
