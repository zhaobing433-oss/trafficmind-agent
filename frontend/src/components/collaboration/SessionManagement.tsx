import { useState } from 'react';
import { Button, Input, Modal, Tag } from 'antd';
import { DeleteOutlined, EditOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons';
import { formatDateTime } from '../../utils/format';
import './sessionManagement.css';

export interface ManagedSession { id: string; title: string; mode: string; updatedAt: number }
export function SessionManagement({ sessions, onOpen, onRename, onDelete }: {
  sessions: ManagedSession[]; onOpen: (id: string) => void;
  onRename: (id: string, title: string) => void; onDelete: (id: string) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null), [title, setTitle] = useState('');
  const save = () => { if (editing && title.trim()) { onRename(editing, title.trim()); setEditing(null); } };
  return <details className="session-management"><summary>会话管理</summary>
    {!sessions.length ? <p>暂无历史会话</p> : sessions.map(session => <div key={session.id} className="session-management-row">
      {editing === session.id ? <Input aria-label="会话名称" value={title} onChange={e => setTitle(e.target.value)} onPressEnter={save} autoFocus />
        : <button className="session-open" onClick={() => onOpen(session.id)}>{session.title || '未命名交通分析'}</button>}
      <Tag>{({ react: '诊断', routed: '研判', rag: '知识库', hybrid: '相似', report: '报告', collaboration: '协同' } as Record<string, string>)[session.mode] || '历史会话'}</Tag>
      <time>{Number.isFinite(session.updatedAt) ? formatDateTime(new Date(session.updatedAt).toISOString()) : '时间未记录'}</time>
      {editing === session.id ? <><Button size="small" icon={<CheckOutlined />} title="保存名称" aria-label="保存名称" onClick={save} disabled={!title.trim()} /><Button size="small" icon={<CloseOutlined />} title="取消修改" aria-label="取消修改" onClick={() => setEditing(null)} /></>
        : <><Button size="small" icon={<EditOutlined />} title="重命名会话" aria-label="重命名会话" onClick={() => { setEditing(session.id); setTitle(session.title); }} />
          <Button size="small" danger icon={<DeleteOutlined />} title="删除会话" aria-label="删除会话" onClick={() => Modal.confirm({ title: '删除分析记录', content: '删除后该分析记录及所有历史轮次都会永久删除，是否继续？', okText: '删除', cancelText: '取消', okType: 'danger', onOk: () => onDelete(session.id) })} /></>}
    </div>)}
  </details>;
}
