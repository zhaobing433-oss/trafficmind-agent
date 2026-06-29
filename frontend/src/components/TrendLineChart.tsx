import ReactECharts from 'echarts-for-react';
import type { StatsResponse } from '../types';

interface Props {
  trend: StatsResponse['dailyTrend'];
}

export default function TrendLineChart({ trend }: Props) {
  const option = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(16,20,52,0.95)',
      borderColor: 'rgba(255,255,255,0.1)',
      textStyle: { color: '#e0e0e0' },
    },
    grid: { left: 10, right: 16, top: 10, bottom: 20 },
    xAxis: {
      type: 'category',
      data: trend.map((d) => d.date.slice(5)),
      axisLabel: { color: 'rgba(255,255,255,0.4)', fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: 'rgba(255,255,255,0.4)', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
    },
    series: [
      {
        type: 'line',
        data: trend.map((d) => d.count),
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: {
          color: '#4facfe',
          width: 2,
        },
        itemStyle: { color: '#4facfe' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(79,172,254,0.25)' },
              { offset: 1, color: 'rgba(79,172,254,0.01)' },
            ],
          },
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
      borderTop: '2px solid #faad14',
    }}>
      <h3 style={{ margin: '0 0 8px', fontSize: 14, color: 'rgba(255,255,255,0.55)', letterSpacing: 1 }}>
        近7日趋势
      </h3>
      <ReactECharts option={option} style={{ height: 260 }} />
    </div>
  );
}
