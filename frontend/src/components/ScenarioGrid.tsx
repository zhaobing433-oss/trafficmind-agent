/**
 * ScenarioGrid — 12 个交通业务场景卡片
 */

const SCENARIOS = [
  { icon: '🏫', title: '学校周边拥堵', desc: '早高峰学校路段，排队超300米', prompt: '学校周边早高峰严重拥堵，平均速度 6km/h，排队长度 320 米，附近有学校，请进行风险研判和处置建议。' },
  { icon: '🏥', title: '医院周边拥堵', desc: '医院急救通道受影响，需优先保障', prompt: '医院周边主干道拥堵，平均速度 8km/h，排队长度 220 米，附近有医院，请分析风险并生成保障方案。' },
  { icon: '🌧', title: '雨天早高峰', desc: '下雨加早高峰，主干道缓行风险高', prompt: '雨天早高峰主干道持续拥堵，平均速度 9km/h，排队长度 180 米，请进行综合风险研判。' },
  { icon: '🚨', title: '突发事故', desc: '交通事故导致车道占用，需快速响应', prompt: '主干道发生交通事故，平均速度骤降至 2km/h，排队长度 400 米，已持续 25 分钟，请研判风险等级并生成处置方案。' },
  { icon: '🚦', title: '信号灯异常', desc: '路口信号灯故障，依赖人工指挥', prompt: '路口信号灯运行异常，多方向车辆积压，请分析影响范围并给出信号优化和临时处置建议。' },
  { icon: '🚧', title: '施工占道', desc: '施工区域占用车道，通行效率下降', prompt: '施工区域占用 2 条车道，高峰期排队超过 200 米，请检查施工合规性并生成交通疏导方案。' },
  { icon: '🏪', title: '商圈散场', desc: '商场散场高峰期，周边路网压力大', prompt: '商圈散场时段周边 3 个路口出现拥堵，请分析路网承载能力并给出分流建议。' },
  { icon: '🛣', title: '高速匝道拥堵', desc: '高速出口匝道排队蔓延至主路', prompt: '高速出口匝道排队长度超过 500 米，已蔓延至主路，请评估安全风险并制定分流策略。' },
  { icon: '🚙', title: '过饱和拥堵', desc: '路口通行能力不足，多周期过饱和', prompt: '路口连续 5 个周期过饱和，进口道排队溢出，请分析通行能力并给出信号配时优化建议。' },
  { icon: '⏳', title: '未闭环风险排查', desc: '系统自动扫描未闭环高风险事件', prompt: '请扫描当前所有未闭环事件，找出其中高风险和重大风险事件，生成排查报告和处置优先级建议。' },
  { icon: '📍', title: '高风险路口分析', desc: '统计近 30 天高风险事件多发路口', prompt: '请分析近 30 天高风险事件多发的路口 Top5，评估每个路口的风险特征和治理建议。' },
  { icon: '📋', title: '日报/周报生成', desc: '一键生成交通事件管理日报或周报', prompt: '请生成本周交通事件周报，包含总体概况、高风险事件、高发路口、类型分布和管理建议。' },
];

interface Props {
  onSelect: (prompt: string, title: string) => void;
}

export default function ScenarioGrid({ onSelect }: Props) {
  return (
    <div>
      <h3 style={{ fontSize: 16, fontWeight: 600, color: '#111827', margin: '0 0 12px' }}>
        常用场景
      </h3>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 10,
      }}>
        {SCENARIOS.map(s => (
          <div
            key={s.title}
            onClick={() => onSelect(s.prompt, s.title)}
            style={{
              background: '#FFF', borderRadius: 16, padding: '14px 16px',
              border: '1px solid #E5E7EB',
              cursor: 'pointer',
              transition: 'border-color 0.15s, box-shadow 0.15s',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = '#0F766E';
              e.currentTarget.style.boxShadow = '0 2px 8px rgba(15,118,110,0.1)';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = '#E5E7EB';
              e.currentTarget.style.boxShadow = '0 1px 3px rgba(0,0,0,0.04)';
            }}
          >
            <div style={{ fontSize: 20, marginBottom: 6 }}>{s.icon}</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#111827', marginBottom: 2 }}>
              {s.title}
            </div>
            <div style={{ fontSize: 11, color: '#9CA3AF', lineHeight: 1.4 }}>
              {s.desc}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
