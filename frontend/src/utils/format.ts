/** 格式化工具函数 */

/** 格式化日期时间 */
export function formatDateTime(dateStr: string): string {
  if (!dateStr) return '-';
  const d = new Date(dateStr);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 风险等级对应颜色 */
export function riskLevelColor(level: string): string {
  const map: Record<string, string> = {
    低风险: '#52c41a',
    中风险: '#faad14',
    高风险: '#ff7a45',
    重大风险: '#ff4d4f',
  };
  return map[level] || '#999';
}

/** 状态对应颜色 */
export function statusColor(status: string): string {
  const map: Record<string, string> = {
    待研判: '#1677ff',
    待派单: '#faad14',
    处置中: '#1677ff',
    已处置: '#52c41a',
    待复盘: '#722ed1',
    已归档: '#999',
  };
  return map[status] || '#999';
}

/** 事件类型对应颜色 */
export function eventTypeColor(type: string): string {
  const map: Record<string, string> = {
    拥堵: '#ff7a45',
    事故: '#ff4d4f',
    违停: '#faad14',
    逆行: '#f5222d',
    行人闯入: '#eb2f96',
    信号灯异常: '#722ed1',
    车辆滞留: '#fa8c16',
    施工占道: '#2f54eb',
  };
  return map[type] || '#666';
}
