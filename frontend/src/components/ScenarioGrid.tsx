/**
 * ScenarioGrid — 12 个交通业务场景卡片
 */

const SCENARIOS = [
  { icon: '🏫', title: '学校周边拥堵', desc: '早高峰学校路段', prompt: '请分析学校周边拥堵事件。地点：人民路学校路段，时间段：早高峰，平均速度：6km/h，排队长度：320米，是否临近学校：是。请给出风险判断、处置建议和公众提示。', mode: 'routed', view: 'analyze' },
  { icon: '🏥', title: '医院周边拥堵', desc: '急救通道需保障', prompt: '请分析医院周边拥堵事件。地点：中心医院周边，平均速度：8km/h，排队长度：220米，是否临近医院：是。请给出保障急救通道的处置方案。', mode: 'routed', view: 'analyze' },
  { icon: '🌧', title: '雨天早高峰', desc: '下雨+高峰叠加风险', prompt: '雨天早高峰出现交通异常。地点：___，事件类型：拥堵，平均速度：___，排队长度：___，天气：雨天，时间段：早高峰。请结合雨天和早高峰特点给出处置建议。', mode: 'routed', view: 'analyze' },
  { icon: '🚨', title: '突发事故', desc: '事故占用车道 · 推荐协同分析', prompt: '道路发生突发事故。地点：___，方向：___，事故类型：追尾，风险等级：高风险，持续时间：25分钟，是否主干道：是，是否临近医院：___。请给出安全风险判断和交通组织建议。', mode: 'collaboration', view: 'multi' },
  { icon: '🚦', title: '信号灯异常', desc: '路口信号故障 · 推荐协同分析', prompt: '路口信号灯疑似异常。地点：___，影响方向：___，排队长度：___，持续时间：___。请分析影响范围、需要哪些Agent协同、是否存在处置冲突，给出融合方案。', mode: 'collaboration', view: 'multi' },
  { icon: '🚧', title: '施工占道', desc: '施工占用车道', prompt: '施工区域占用车道。地点：___，高峰期排队超过200米，请检查施工合规性并生成交通疏导方案。', mode: 'routed', view: 'analyze' },
  { icon: '🏪', title: '商圈散场', desc: '散场期路网压力', prompt: '商圈散场时段周边路口出现拥堵，请分析路网承载能力并给出分流建议。', mode: 'react', view: 'home' },
  { icon: '🛣', title: '高速匝道拥堵', desc: '匝道排队蔓延主路', prompt: '高速出口匝道排队超过500米已蔓延至主路，请评估安全风险并制定分流策略。', mode: 'react', view: 'home' },
  { icon: '🚙', title: '过饱和拥堵', desc: '路口通行能力不足', prompt: '路口连续5个周期过饱和，进口道排队溢出，请分析通行能力并给出信号配时优化建议。', mode: 'react', view: 'home' },
  { icon: '⏳', title: '未闭环风险排查', desc: '扫描未闭环高风险', prompt: '请扫描当前所有未闭环事件，找出高风险和重大风险事件，生成排查报告和处置优先级建议。', mode: 'react', view: 'alert' },
  { icon: '📍', title: '高风险路口分析', desc: '统计高风险多发路口', prompt: '请分析近30天高风险事件多发的路口Top5，评估每个路口的风险特征和治理建议。', mode: 'report', view: 'report' },
  { icon: '📋', title: '日报/周报生成', desc: '一键生成管理报告', prompt: '请生成本周交通事件周报，包含总体概况、高风险事件、高发路口、类型分布和管理建议。', mode: 'report', view: 'report' },
];

interface Props {
  onSelect: (prompt: string, mode: string, targetView: string) => void;
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
            onClick={() => onSelect(s.prompt, s.mode, s.view)}
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
