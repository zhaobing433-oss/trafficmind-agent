/**
 * WorkflowObservabilityView — Phase 14 可观察性视图
 * 给用户理解 Workflow，不是原始审计 Timeline。
 */
import React, { useEffect, useState } from 'react';
import { getWorkflowObservability } from '../../api/observabilityApi';
import type { WorkflowObservability, NodeObservation } from '../../types/observability';

interface Props { runId: string }

const STATUS_LABELS: Record<string,string> = {
  pending:'等待中',running:'运行中',paused:'已暂停',awaiting_approval:'等待审批',
  completed:'已完成',failed:'失败',cancelled:'已取消',rejected:'已驳回',
};
const NODE_STATUS_LABELS: Record<string,string> = {
  pending:'等待',running:'运行中',succeeded:'成功',failed:'失败',retrying:'重试中',skipped:'跳过',
};
const STATUS_COLORS: Record<string,string> = {
  running:'#3B82F6',awaiting_approval:'#F59E0B',completed:'#0F766E',failed:'#EF4444',rejected:'#EF4444',
};

export const WorkflowObservabilityView: React.FC<Props> = ({ runId }) => {
  const [data, setData] = useState<WorkflowObservability | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<NodeObservation | null>(null);
  const [tab, setTab] = useState<'overview'|'nodes'|'audit'>('overview');

  useEffect(() => {
    let cancelled = false;
    getWorkflowObservability(runId).then(d => { if (!cancelled) setData(d); }).catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [runId]);

  if (error) return <div style={{ padding:16,color:'#EF4444',fontSize:13 }}>可观察性数据加载失败: {error}<br/><button onClick={()=>{setError(null);setData(null);}} style={{marginTop:8,cursor:'pointer'}}>重试</button></div>;
  if (!data) return <div style={{ padding:16,color:'#9CA3AF',fontSize:13 }}>加载中...</div>;

  const m = data.metrics as Record<string,number>;
  const showOutcome = data.simulation_refs && Object.keys(data.simulation_refs).length > 0;

  return (
    <div style={{ fontSize:12 }}>
      {/* Tabs */}
      <div style={{ display:'flex',gap:2,marginBottom:12,borderBottom:'1px solid #E5E7EB' }}>
        {(['overview','nodes','audit'] as const).map(t => (
          <button key={t} onClick={()=>setTab(t)}
            style={{ padding:'6px 16px',border:'none',background:tab===t?'#F0FDFA':'transparent',color:tab===t?'#0F766E':'#6B7280',cursor:'pointer',fontSize:12,fontWeight:tab===t?600:400,borderBottom:tab===t?'2px solid #0F766E':'2px solid transparent' }}>
            {t==='overview'?'概览':t==='nodes'?'流程节点':'审计时间线'}</button>
        ))}
      </div>

      {tab === 'overview' && (
        <div style={{ display:'flex',flexDirection:'column',gap:10 }}>
          {/* Summary */}
          <Card title="Workflow 概览">
            <Row label="名称" value={data.definition_name} />
            <Row label="状态" value={STATUS_LABELS[data.status]||data.status} color={STATUS_COLORS[data.status]} />
            <Row label="Run ID" value={data.run_id.slice(0,24)+'...'} />
            <Row label="开始时间" value={data.started_at?.slice(0,19)||'—'} />
            {data.completed_at && <Row label="结束时间" value={data.completed_at.slice(0,19)} />}
            <Row label="总耗时" value={data.total_duration_ms>0?`${(data.total_duration_ms/1000).toFixed(1)}s`:'—'} />
          </Card>

          {/* Metrics */}
          <Card title="指标">
            <Row label="节点总数" value={m.node_count} />
            <Row label="成功" value={m.succeeded} color="#0F766E" />
            <Row label="失败" value={m.failed} color={m.failed>0?'#EF4444':undefined} />
            <Row label="重试次数" value={m.retried} />
            <Row label="Action 数量" value={m.action_count} />
            {data.approval && <Row label="审批结果" value={data.approval.decision==='approved'?'已批准':data.approval.decision==='rejected'?'已驳回':data.approval.decision} />}
          </Card>

          {/* Outcome */}
          {showOutcome && data.actions.length > 0 && data.actions[0].improvement && Object.keys(data.actions[0].improvement).length > 0 && (
            <Card title="处置效果">
              {(()=>{ const imp=data.actions[0].improvement; return (<>
                <Row label="速度" value={`${String(imp.speed_before??'?')} → ${String(imp.speed_after??'?')} km/h`} color={Number(imp.speed_delta)>0?'#0F766E':undefined} />
                <Row label="排队" value={`${String(imp.queue_before??'?')} → ${String(imp.queue_after??'?')} m`} color={Number(imp.queue_delta)<0?'#0F766E':undefined} />
                <Row label="拥堵" value={`${String(imp.congestion_before??'?')} → ${String(imp.congestion_after??'?')}`} color="#0F766E" />
              </>); })()}
            </Card>
          )}
          {showOutcome && (!data.actions.length || !data.actions[0].improvement || !Object.keys(data.actions[0].improvement).length) && (
            <Card title="处置效果"><Muted>处置前后快照数据暂不可用</Muted></Card>
          )}
        </div>
      )}

      {tab === 'nodes' && (
        <div style={{ display:'flex',gap:12 }}>
          {/* Step List */}
          <div style={{ width:220,flexShrink:0 }}>
            {data.nodes.map(n => (
              <div key={n.node_id} onClick={()=>setSelectedNode(n)}
                style={{ padding:'7px 10px',cursor:'pointer',borderRadius:6,background:selectedNode?.node_id===n.node_id?'#F0FDFA':'transparent',marginBottom:2,display:'flex',alignItems:'center',gap:6 }}>
                <span style={{ fontSize:14 }}>{n.status==='succeeded'?'✓':n.status==='failed'?'✗':n.status==='running'?'●':'○'}</span>
                <div style={{ flex:1,minWidth:0 }}>
                  <div style={{ fontSize:11,fontWeight:selectedNode?.node_id===n.node_id?600:400,color:'#111827' }}>{n.display_name}</div>
                  <div style={{ fontSize:9,color:'#9CA3AF' }}>{n.node_type}{n.attempt>1?` · 第${n.attempt}次`:''}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Node Detail */}
          <div style={{ flex:1 }}>
            {selectedNode ? (
              <Card title={selectedNode.display_name}>
                <div style={{ fontSize:10,color:'#9CA3AF',marginBottom:8 }}>{selectedNode.node_id} · {selectedNode.node_type}</div>
                {selectedNode.description && <div style={{ marginBottom:8,color:'#374151' }}>{selectedNode.description}</div>}
                <Row label="状态" value={NODE_STATUS_LABELS[selectedNode.status]||selectedNode.status} />
                <Row label="耗时" value={selectedNode.duration_ms>0?`${selectedNode.duration_ms}ms`:'—'} />
                {selectedNode.attempt>1 && <Row label="尝试次数" value={selectedNode.attempt} />}
                {selectedNode.error && <div style={{ marginTop:8,padding:'6px 8px',background:'#FEF2F2',borderRadius:6,color:'#DC2626',fontSize:11 }}>{selectedNode.error}</div>}

                {/* Agent-specific */}
                {selectedNode.node_type==='agent_task' && data.agent && (
                  <div style={{ marginTop:8 }}>
                    <div style={{ fontWeight:600,marginBottom:4 }}>{data.agent.agent_name}</div>
                    {data.agent.proposed_actions.length>0 && (
                      <div style={{ marginTop:4 }}>
                        <div style={{ fontSize:10,color:'#6B7280',marginBottom:2 }}>处置建议:</div>
                        {data.agent.proposed_actions.map((pa,i) => (
                          <div key={i} style={{ background:'#F9FAFB',borderRadius:6,padding:'6px 8px',fontSize:11,marginBottom:4 }}>
                            <strong>{pa.actionType as string}</strong>
                            <div style={{ color:'#6B7280' }}>{pa.sourceRoadId as string} → {(pa.targetRoadIds as string[])?.join(' / ')}</div>
                            <div>分流: {((pa.diversionRatio as number||0)*100).toFixed(0)}%</div>
                            {pa.rationale ? <div style={{ fontSize:10,color:'#9CA3AF',marginTop:2 }}>{String(pa.rationale).slice(0,120)}</div> : null}
                          </div>
                        ))}
                      </div>
                    )}
                    {(!data.agent.tool_calls || data.agent.tool_calls.length===0) && (
                      <Muted>本次 Agent 使用预构建空间上下文，未执行独立工具调用。</Muted>
                    )}
                  </div>
                )}

                {/* Approval-specific */}
                {selectedNode.node_type==='human_approval' && data.approval && (
                  <div style={{ marginTop:8 }}>
                    <div style={{ color:'#374151',marginBottom:4 }}>
                      Agent 已提出会改变交通仿真世界状态的处置动作。Workflow 在真正执行动作前暂停，等待人工确认。
                    </div>
                    <Row label="审批结果" value={data.approval.decision==='approved'?'已批准':data.approval.decision} />
                    {data.approval.proposed_actions.length>0 && (
                      <div style={{ marginTop:4 }}>
                        <div style={{ fontSize:10,color:'#6B7280' }}>Proposal: {data.approval.proposed_actions[0].actionType as string}</div>
                      </div>
                    )}
                  </div>
                )}

                {/* Action-specific */}
                {selectedNode.node_type==='action' && data.actions.length>0 && (
                  <div style={{ marginTop:8 }}>
                    {data.actions.map((a,i) => (
                      <div key={i} style={{ marginBottom:6 }}>
                        <Row label="类型" value={a.action_type} />
                        <Row label="状态" value={a.status} />
                        {a.improvement && Object.keys(a.improvement).length>0 && (()=>{ const imp=a.improvement; return (
                          <div style={{ marginTop:4 }}>
                            <div style={{ fontSize:10,color:'#6B7280',marginBottom:2 }}>处置效果:</div>
                            <div style={{ display:'flex',gap:12,fontSize:11 }}>
                              <span>速度: {String(imp.speed_before)}→{String(imp.speed_after)}</span>
                              <span>排队: {String(imp.queue_before)}→{String(imp.queue_after)}</span>
                            </div>
                          </div>
                        );})()}
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            ) : (
              <Muted>← 点击左侧节点查看详情</Muted>
            )}
          </div>
        </div>
      )}

      {tab === 'audit' && (
        <div style={{ display:'flex',flexDirection:'column',gap:4 }}>
          {data.nodes.map(n => (
            <div key={n.node_id} style={{ padding:'4px 8px',background:n.status==='failed'?'#FEF2F2':'#F9FAFB',borderRadius:4,fontSize:10 }}>
              <span style={{ marginRight:8,color:n.status==='succeeded'?'#0F766E':n.status==='failed'?'#EF4444':'#6B7280' }}>{n.status}</span>
              <span style={{ color:'#111827' }}>{n.display_name}</span>
              <span style={{ color:'#9CA3AF',marginLeft:8 }}>{n.node_id}</span>
              {n.duration_ms>0 && <span style={{ color:'#9CA3AF',marginLeft:8 }}>{n.duration_ms}ms</span>}
              {n.attempt>1 && <span style={{ color:'#F59E0B',marginLeft:8 }}>retry×{n.attempt}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const Card: React.FC<{title:string;children:React.ReactNode}> = ({title,children}) => (
  <div style={{ background:'#FFF',borderRadius:10,border:'1px solid #E5E7EB',padding:'10px 14px' }}>
    <div style={{ fontSize:11,fontWeight:700,color:'#111827',marginBottom:6 }}>{title}</div>
    {children}
  </div>
);
const Row: React.FC<{label:string;value:string|number;color?:string}> = ({label,value,color}) => (
  <div style={{ display:'flex',justifyContent:'space-between',padding:'2px 0',fontSize:11 }}>
    <span style={{ color:'#9CA3AF' }}>{label}</span>
    <span style={{ fontWeight:600,color:color||'#374151' }}>{value}</span>
  </div>
);
const Muted: React.FC<{children:React.ReactNode}> = ({children}) => <div style={{ color:'#9CA3AF',fontSize:11 }}>{children}</div>;
