import ReactECharts from 'echarts-for-react';
import type { StatsResponse } from '../types';
import { riskLevelColor } from '../utils/format';

interface Props {
  distribution: StatsResponse['riskDistribution'];
}

export default function RiskPieChart({ distribution }: Props) {
  const sorted = [...distribution].sort((a, b) => {
    const order = ['重大风险', '高风险', '中风险', '低风险'];
    return order.indexOf(a.level) - order.indexOf(b.level);
  });

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} 条 ({d}%)',
      backgroundColor: 'rgba(16,20,52,0.95)',
      borderColor: 'rgba(255,255,255,0.1)',
      textStyle: { color: '#e0e0e0' },
    },
    legend: {
      bottom: 0,
      textStyle: { color: 'rgba(255,255,255,0.55)', fontSize: 12 },
    },
    series: [
      {
        name: '风险分布',
        type: 'pie',
        radius: ['50%', '75%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 4,
          borderColor: 'rgba(10,14,39,0.8)',
          borderWidth: 3,
        },
        label: {
          show: true,
          position: 'outside',
          formatter: '{b}\n{d}%',
          color: 'rgba(255,255,255,0.6)',
          fontSize: 11,
        },
        emphasis: {
          label: { fontSize: 16, fontWeight: 'bold' },
        },
        data: sorted.map((d) => ({
          value: d.count,
          name: d.level,
          itemStyle: { color: riskLevelColor(d.level) },
        })),
      },
    ],
  };

  return (
    <div style={{
      background: 'rgba(16,20,52,0.7)',
      backdropFilter: 'blur(10px)',
      border: '1px solid rgba(255,255,255,0.06)',
      borderRadius: 8,
      padding: '16px',
      borderTop: '2px solid #722ed1',
    }}>
      <h3 style={{ margin: '0 0 8px', fontSize: 14, color: 'rgba(255,255,255,0.55)', letterSpacing: 1 }}>
        风险分布
      </h3>
      <ReactECharts option={option} style={{ height: 260 }} />
    </div>
  );
}
