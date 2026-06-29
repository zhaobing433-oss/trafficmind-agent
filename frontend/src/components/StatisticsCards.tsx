import type { StatsResponse } from '../types';

interface Props {
  stats: StatsResponse | null;
}

const cardStyle: React.CSSProperties = {
  background: 'rgba(16, 20, 52, 0.7)',
  backdropFilter: 'blur(10px)',
  border: '1px solid rgba(255,255,255,0.06)',
  borderRadius: 8,
  padding: '20px 24px',
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
};

const labelStyle: React.CSSProperties = {
  fontSize: 13,
  color: 'rgba(255,255,255,0.45)',
  letterSpacing: 1,
};

const valueStyle: React.CSSProperties = {
  fontSize: 32,
  fontWeight: 700,
  letterSpacing: 1,
};

const iconStyle: React.CSSProperties = {
  fontSize: 40,
  opacity: 0.3,
  position: 'absolute' as const,
  right: 16,
  top: 12,
};

export default function StatisticsCards({ stats }: Props) {
  const cards = [
    {
      label: '事件总数',
      value: stats?.totalEvents ?? '-',
      color: '#4facfe',
      icon: '📊',
    },
    {
      label: '高风险事件',
      value: stats?.highRiskCount ?? '-',
      color: '#ff4d4f',
      icon: '🚨',
    },
    {
      label: '平均风险分',
      value: stats?.avgRiskScore ?? '-',
      color: '#faad14',
      icon: '📈',
    },
    {
      label: '待派单数',
      value: stats?.pendingDispatch ?? '-',
      color: '#ff7a45',
      icon: '📋',
    },
  ];

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 16,
      marginBottom: 16,
    }}>
      {cards.map((card) => (
        <div key={card.label} style={{ ...cardStyle, position: 'relative', borderTop: `2px solid ${card.color}` }}>
          <span style={labelStyle}>{card.label}</span>
          <span style={{ ...valueStyle, color: card.color }}>{card.value}</span>
          <span style={iconStyle}>{card.icon}</span>
        </div>
      ))}
    </div>
  );
}
