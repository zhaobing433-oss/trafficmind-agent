import type { CSSProperties } from 'react';

const sections = [
  {
    title: '产品逻辑',
    body: '首次发送会自动创建会话；同一会话内追问会继续保留在当前会话。左侧工作区决定页面入口，输入框能力决定本次问题调用的分析链路。',
  },
  {
    title: '知识问答',
    body: '知识库问答以检索证据为依据，召回、重排、阈值过滤后再生成回答。证据不足时会明确拒答，不用猜测补齐。',
  },
  {
    title: '跨页关系',
    body: '事件、会话、工作流运行、计划和评测之间只展示数据库中真实存在的关系。没有持久化关系时显示空态，不构造演示绑定。',
  },
  {
    title: '工作流与计划',
    body: '工作流详情展示运行时间线、节点、审批、动作和安全投影后的决策链；计划中心展示计划版本、执行血缘和重规划轨迹。',
  },
];

export function GuidePage() {
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <header>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>文档指南</h2>
        <p style={{ fontSize: 13, color: '#6B7280', margin: 0 }}>工作台能力边界与数据口径</p>
      </header>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}>
        {sections.map(section => (
          <section key={section.title} style={panelStyle}>
            <h3 style={{ fontSize: 15, fontWeight: 600, color: '#111827', margin: '0 0 8px' }}>{section.title}</h3>
            <p style={{ fontSize: 13, color: '#4B5563', lineHeight: 1.7, margin: 0 }}>{section.body}</p>
          </section>
        ))}
      </div>
    </div>
  );
}

const panelStyle: CSSProperties = {
  background: '#FFF',
  borderRadius: 8,
  padding: 16,
  border: '1px solid #E5E7EB',
};
