/**
 * HomeHero — 首页标题区 + 状态卡片
 */
import StatusCards from './StatusCards';

export default function HomeHero() {
  return (
    <div style={{ textAlign: 'center', padding: '36px 24px 20px' }}>
      <h1 style={{
        fontSize: 32, fontWeight: 800, color: '#111827', margin: 0,
        letterSpacing: 0,
      }}>
        TrafficMind <span style={{ color: '#0F766E' }}>Agent</span>
      </h1>
      <p style={{
        fontSize: 15, color: '#6B7280', margin: '8px 0 4px',
      }}>
        智慧交通事件研判与协同决策工作台
      </p>
      <p style={{
        fontSize: 12, color: '#9CA3AF', maxWidth: 520, margin: '0 auto 24px',
      }}>
        支持交通知识检索、相似案例、协同研判和闭环处置分析
      </p>
      <StatusCards />
    </div>
  );
}
