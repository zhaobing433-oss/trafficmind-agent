import { actionName } from '../../utils/closedLoop';
import { record, text } from '../../utils/judgment';

export function ApprovalActionSummary({ action, context = {} }: { action: Record<string, unknown>; context?: Record<string, unknown> }) {
  const params = record(action.params || action.action_params || action.parameterHints);
  const fields: Record<string, string> = { message: '通知内容', content: '内容', title: '标题', roadName: '道路', target: '目标', recipient: '接收方', department: '部门', priority: '优先级', duration: '时长', diversionRatio: '分流比例' };
  const values = Object.entries(params).filter(([key, value]) => fields[key] && ['string', 'number', 'boolean'].includes(typeof value));
  const riskScore = context.riskScore;
  return <div className="execution-step"><strong>{actionName(action)}</strong>
    <div>操作目标：{text(action.target) || text(params.target) || text(params.roadName) || text(context.roadName) || '未记录'}</div>
    <div className="execution-muted">已有理由：{text(action.reason) || text(context.reason) || '未记录'}</div>
    <div className="execution-muted">已有风险：{text(context.riskLevel) || '未记录'}{typeof riskScore === 'number' && Number.isFinite(riskScore) ? ` · 风险评分 ${riskScore}` : ''}</div>
    {values.length ? values.map(([key, value]) => <div className="execution-muted" key={key}>{fields[key]}：{String(value)}</div>) : <div className="execution-muted">业务参数未记录</div>}
    <details className="execution-muted"><summary>技术参数</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(action, null, 2)}</pre></details>
  </div>;
}
