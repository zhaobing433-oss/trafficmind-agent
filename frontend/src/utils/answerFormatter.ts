/**
 * answerFormatter — 将接口返回转成自然语言对话风格
 */

type R = Record<string, unknown>;

export function formatAssistantAnswer(mode: string, result: R | null, question: string): string {
  if (!result) return '分析完成，请查看下方详细依据。';

  switch (mode) {
    case 'react': return formatReact(result, question);
    case 'rag': return formatRag(result, question);
    case 'routed': return formatRouted(result, question);
    case 'hybrid': return formatHybrid(result, question);
    case 'report': return formatReport(result, question);
    default: return formatReact(result, question);
  }
}

function formatReact(r: R, q: string): string {
  const lines: string[] = [];
  const answer = (r.finalAnswer as string) || '';
  const warnings = r.warnings as string[] | undefined;

  if (answer) {
    lines.push(answer);
  } else {
    // Build natural summary
    lines.push('根据系统分析，针对您的问题"' + q.slice(0, 40) + '"，以下是诊断结论：');
    lines.push('');

    const steps = r.steps as R[] | undefined;
    if (steps && steps.length > 0) {
      const tools = steps.map(s => s.action).filter(Boolean);
      lines.push('系统依次调用了 ' + tools.join('、') + ' 等工具进行数据采集和分析。');
      lines.push('');
    }

    lines.push('建议如下：');
    lines.push('1. 关注高风险路段和未闭环事件，优先处置重大风险事件。');
    lines.push('2. 结合实时天气和时段信息调整信号配时和巡查频次。');
    lines.push('3. 对高频事件路段组织专项排查，从源头减少事件发生。');
    lines.push('');
    lines.push('详细数据和依据请见下方"查看详细依据"。');
  }

  if (warnings && warnings.length) {
    lines.push('');
    lines.push('注意事项：');
    warnings.forEach(w => lines.push('· ' + w));
  }

  return lines.join('\n');
}

function formatRag(r: R, q: string): string {
  const answer = r.answer as string;
  if (answer) return answer;

  const evidence = r.evidence as R[] | undefined;
  if (!evidence || evidence.length === 0) {
    return '当前知识库中未检索到与"' + q.slice(0, 30) + '"直接相关的依据。\n\n建议：\n1. 点击下方"重建 RAG 索引"按钮更新知识库\n2. 或尝试用更具体的交通术语提问\n3. 也可以查看文档指南了解系统能力';
  }

  const lines: string[] = [];
  lines.push('根据交通知识库检索，关于"' + q.slice(0, 30) + '"的相关依据如下：');
  lines.push('');
  evidence.slice(0, 4).forEach((e, i) => {
    const docType = e.docType as string || '';
    const typeLabel: Record<string, string> = { rule: '处置预案', dispatch_experience: '调度经验', event_report: '历史案例', daily_report: '日报' };
    lines.push((i + 1) + '. [' + (typeLabel[docType] || docType) + '] ' + (e.content as string || '').slice(0, 120) + '...');
  });
  lines.push('');
  lines.push('以上为检索到的知识依据，详细内容请见下方"查看详细依据"。');
  return lines.join('\n');
}

function formatRouted(r: R, q: string): string {
  const lines: string[] = [];
  const agents = r.selectedAgents as string[] | undefined;
  const reasons = r.routingReasons as string[] | undefined;
  const conflicts = r.conflicts as unknown[] | undefined;
  const decision = r.finalDecision as string || '';
  const plan = r.dispatchPlan as R | undefined;

  lines.push('针对您提交的事件，系统已完成多Agent协同研判：');
  lines.push('');

  if (agents && agents.length) {
    lines.push('参与研判的Agent：' + agents.join('、') + '。');
  }
  if (reasons && reasons.length) {
    lines.push('路由原因：' + reasons.slice(0, 3).join('；') + '。');
  }
  if (decision) {
    lines.push('');
    lines.push('综合结论：' + decision);
  }
  if (plan) {
    lines.push('紧急度：' + (plan.urgency as string || '待评估'));
    const actions = plan.actions as string[] | undefined;
    if (actions && actions.length) {
      lines.push('处置方案已生成（' + actions.length + '条），详见下方。');
    }
  }
  if (conflicts && conflicts.length) {
    lines.push('');
    lines.push('检测到 ' + conflicts.length + ' 个Agent建议冲突，已自动融合处理。');
  }

  return lines.join('\n');
}

function formatHybrid(r: R, q: string): string {
  const cases = r.similarCases as R[] | undefined;
  if (!cases || cases.length === 0) {
    return '未找到相似历史案例。\n\n混合相似检索基于历史事件记录和向量知识库，综合规则相似度（权重0.6）和语义相似度（权重0.4）进行召回。如数据库为空，请先通过事件研判录入事件数据。';
  }

  const lines: string[] = [];
  lines.push('共检索到 ' + cases.length + ' 个相似历史案例：');
  lines.push('');

  const top = cases[0];
  lines.push('最相似案例：' + top.eventId + ' — ' + top.roadName + '（' + top.eventType + '）');
  lines.push('· 规则相似度：' + (Number(top.ruleSimilarity || 0) * 100).toFixed(0) + '%');
  lines.push('· 向量相似度：' + (Number(top.vectorSimilarity || 0) * 100).toFixed(0) + '%');
  lines.push('· 综合相似度：' + (Number(top.finalSimilarity || 0) * 100).toFixed(0) + '%');

  if (cases.length > 1) {
    lines.push('');
    lines.push('其他相似案例：');
    cases.slice(1, 5).forEach(c => {
      lines.push('· ' + c.eventId + ' — ' + c.roadName + '（综合' + (Number(c.finalSimilarity || 0) * 100).toFixed(0) + '%）');
    });
  }

  lines.push('');
  lines.push('注：相似案例基于历史事件记录和向量知识库，非聊天记录。');
  return lines.join('\n');
}

function formatReport(r: R, q: string): string {
  const lines: string[] = [];
  const keyFindings = r.keyFindings as string[] | undefined;
  const suggestions = r.suggestions as string[] | undefined;
  const totalEvents = r.totalEvents as number | undefined;

  lines.push('已生成交通事件报告：');
  lines.push('');

  if (totalEvents !== undefined) {
    lines.push('报告期内共发生 ' + totalEvents + ' 起交通事件，');
    const highRisk = (r.highRiskEvents as number) || 0;
    lines.push('其中高风险 ' + highRisk + ' 起');
    if (r.majorRiskEvents) lines.push('（含重大风险 ' + r.majorRiskEvents + ' 起）');
    lines.push('。');
  }

  if (keyFindings && keyFindings.length) {
    lines.push('');
    lines.push('关键发现：');
    keyFindings.slice(0, 4).forEach(f => lines.push('· ' + f));
  }

  if (suggestions && suggestions.length) {
    lines.push('');
    lines.push('管理建议：');
    suggestions.slice(0, 4).forEach(s => lines.push('· ' + s));
  }

  lines.push('');
  lines.push('完整报告内容请见下方"查看详细报告"。');
  return lines.join('\n');
}
