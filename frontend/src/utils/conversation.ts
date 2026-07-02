/** localStorage 会话管理 — 含存储控制、标题自动总结、上下文压缩 */

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  mode: string;
  content: string;
  timestamp: number;
  /** 精简后的 result，不保存完整原始 JSON */
  summaryResult?: SummaryResult;
}

export interface SummaryResult {
  confidence?: number;
  usedLLM?: boolean;
  evidenceCount?: number;
  conflictsCount?: number;
  agentsCount?: number;
  casesCount?: number;
  urgency?: string;
}

export interface Conversation {
  id: string;
  title: string;
  mode: string;
  messages: Message[];
  createdAt: number;
  updatedAt: number;
}

const CONV_PREFIX = 'trafficmind_conv_';
const RECENT_KEY = 'trafficmind_recent';
const MAX_CONVERSATIONS = 50;
const MAX_MESSAGES_PER_CONV = 30;
const MAX_CONTENT_LEN = 3000;

// ========== CRUD ==========

export function createConversation(title: string, mode: string): Conversation {
  return { id: 'conv_' + Date.now(), title, mode, messages: [], createdAt: Date.now(), updatedAt: Date.now() };
}

export function saveConversation(conv: Conversation): void {
  conv.updatedAt = Date.now();
  // Trim messages
  if (conv.messages.length > MAX_MESSAGES_PER_CONV) {
    conv.messages = conv.messages.slice(-MAX_MESSAGES_PER_CONV);
  }
  // Trim content
  conv.messages = conv.messages.map(m => ({
    ...m,
    content: m.content.slice(0, MAX_CONTENT_LEN),
  }));

  try { localStorage.setItem(CONV_PREFIX + conv.id, JSON.stringify(conv)); } catch {
    cleanupOldConversations();
    try { localStorage.setItem(CONV_PREFIX + conv.id, JSON.stringify(conv)); } catch { /* quota still exceeded */ }
  }

  updateRecentList(conv);
}

export function loadConversation(id: string): Conversation | null {
  try {
    const raw = localStorage.getItem(CONV_PREFIX + id);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

export function getRecentConversations(): { id: string; title: string; mode: string; updatedAt: number }[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

// ========== Recent list management ==========

function updateRecentList(conv: Conversation) {
  const recent = getRecentConversations();
  const idx = recent.findIndex(r => r.id === conv.id);
  const entry = { id: conv.id, title: conv.title, mode: conv.mode, updatedAt: conv.updatedAt };
  if (idx >= 0) recent[idx] = entry;
  else recent.unshift(entry);
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(recent.slice(0, 20))); } catch { /* ignore */ }
}

function cleanupOldConversations() {
  const recent = getRecentConversations();
  // Remove oldest entries beyond MAX_CONVERSATIONS
  const toRemove = recent.slice(MAX_CONVERSATIONS);
  toRemove.forEach(r => {
    try { localStorage.removeItem(CONV_PREFIX + r.id); } catch { /* ignore */ }
  });
  // Trim recent list
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(recent.slice(0, MAX_CONVERSATIONS))); } catch { /* ignore */ }
  console.warn('[TrafficMind] 本地存储已满，已自动清理旧会话');
}

// ========== Title generation ==========

export function generateConversationTitle(messages: Message[], latestQuestion: string): string {
  const allText = messages.map(m => m.content).join(' ') + ' ' + latestQuestion;

  // Rule-based matching
  if (allText.includes('医院') && (allText.includes('拥堵') || allText.includes('排队'))) return '医院周边拥堵处置';
  if (allText.includes('学校')) return '学校周边交通研判';
  if (allText.includes('高风险') && allText.includes('原因')) return '高风险原因分析';
  if (allText.includes('未闭环')) return '未闭环事件排查';
  if (allText.includes('信号灯') || allText.includes('信号异常')) return '信号灯异常协同研判';
  if (allText.includes('事故') && (allText.includes('突发') || allText.includes('碰撞'))) return '突发事故处置建议';
  if (allText.includes('事故')) return '事故应急处置';
  if (allText.includes('施工') || allText.includes('占道')) return '施工占道疏导方案';
  if (allText.includes('匝道') || allText.includes('高速')) return '高速匝道拥堵分析';
  if (allText.includes('散场') || allText.includes('商圈')) return '商圈散场交通疏导';
  if (allText.includes('过饱和') || allText.includes('通行能力')) return '过饱和路口优化';
  if (allText.includes('高峰') && allText.includes('雨')) return '雨天高峰拥堵分析';
  if (allText.includes('高峰')) return '高峰时段交通研判';
  if (allText.includes('日报') || allText.includes('周报')) return '交通事件报告生成';
  if (allText.includes('逆行')) return '逆行事件风险评估';
  if (allText.includes('行人')) return '行人闯入安全评估';
  if (allText.includes('违停')) return '违停事件处置';
  if (allText.includes('滞留')) return '车辆滞留事件排查';

  // Fallback
  return latestQuestion.slice(0, 16) + (latestQuestion.length > 16 ? '...' : '');
}

// ========== Context compression ==========

export function buildConversationSummary(messages: Message[]): string {
  if (messages.length <= 6) {
    return messages.filter(m => m.role !== 'system').map(m =>
      '[' + (m.role === 'user' ? '用户' : '助手') + ']: ' + m.content.slice(0, 200)
    ).join('\n');
  }

  // Generate summary from longer conversations
  const userMessages = messages.filter(m => m.role === 'user').map(m => m.content);
  const allText = userMessages.join(' ');
  const parts: string[] = [];

  // Extract key topics
  if (allText.includes('医院')) parts.push('讨论涉及医院周边交通');
  if (allText.includes('学校')) parts.push('讨论涉及学校路段');
  if (allText.includes('事故')) parts.push('讨论了事故处置方案');
  if (allText.includes('拥堵')) parts.push('讨论了拥堵治理措施');
  if (allText.includes('信号')) parts.push('讨论了信号灯相关问题');
  if (allText.includes('高风险')) parts.push('关注高风险路口和事件');

  const summary = parts.length > 0 ? parts.join('；') + '。' : '用户进行了多轮交通管理咨询。';

  // Keep last 4 messages
  const recent = messages.slice(-4).map(m =>
    '[' + (m.role === 'user' ? '用户' : '助手') + ']: ' + m.content.slice(0, 200)
  ).join('\n');

  return '对话摘要：' + summary + '\n\n最近对话：\n' + recent;
}

// ========== Contextual question building ==========

export function buildContextualQuestion(conv: Conversation, currentQuestion: string): string {
  if (conv.messages.length === 0) return currentQuestion;
  const summary = buildConversationSummary(conv.messages);
  return '历史对话摘要：\n' + summary + '\n\n当前问题：' + currentQuestion;
}

// ========== Summary result extraction ==========

export function extractSummaryResult(result: Record<string, unknown> | null): SummaryResult | undefined {
  if (!result) return undefined;
  return {
    confidence: typeof result.confidence === 'number' ? result.confidence : undefined,
    usedLLM: typeof result.usedLLM === 'boolean' ? result.usedLLM : undefined,
    evidenceCount: Array.isArray(result.evidence) ? result.evidence.length : undefined,
    conflictsCount: Array.isArray(result.conflicts) ? result.conflicts.length : undefined,
    agentsCount: Array.isArray(result.selectedAgents) ? result.selectedAgents.length : undefined,
    casesCount: Array.isArray(result.similarCases) ? result.similarCases.length : undefined,
    urgency: (result.dispatchPlan as Record<string,unknown>)?.urgency as string || undefined,
  };
}
