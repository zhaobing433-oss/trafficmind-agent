import ReactECharts from 'echarts-for-react';
import type { StatsResponse } from '../types';
import { eventTypeColor } from '../utils/format';

interface Props {
  distribution: StatsResponse['eventTypeDistribution'];
}

export default function EventTypeBarChart({ distribution }: Props) {
  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(16,20,52,0.95)',
      borderColor: 'rgba(255,255,255,0.1)',
      textStyle: { color: '#e0e0e0' },
    },
    grid: { left: 10, right: 20, top: 10, bottom: 20 },
    xAxis: {
      type: 'value',
      axisLabel: { color: 'rgba(255,255,255,0.4)', fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
    },
    yAxis: {
      type: 'category',
      data: distribution.map((d) => d.type).reverse(),
      axisLabel: { color: 'rgba(255,255,255,0.55)', fontSize: 11 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        type: 'bar',
        data: distribution
          .map((d) => ({
            value: d.count,
            itemStyle: { color: eventTypeColor(d.type), borderRadius: [0, 4, 4, 0] },
          }))
          .reverse(),
        barWidth: 16,
        label: {
          show: true,
          position: 'right',
          color: 'rgba(255,255,255,0.5)',
          fontSize: 11,
        },
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
      borderTop: '2px solid #4facfe',
    }}>
      <h3 style={{ margin: '0 0 8px', fontSize: 14, color: 'rgba(255,255,255,0.55)', letterSpacing: 1 }}>
        事件类型
      </h3>
      <ReactECharts option={option} style={{ height: 260 }} />
    </div>
  );
}
