/** Chat 会话 API — 后端会话持久化 */

const API = '/api';

async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error((await r.json().catch(() => ({ detail: `HTTP ${r.status}` }))).detail || '请求失败');
  return r.json();
}
async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({ detail: `HTTP ${r.status}` }))).detail || '请求失败');
  return r.json();
}
async function apiDelete(path: string): Promise<void> {
  const r = await fetch(`${API}${path}`, { method: 'DELETE' });
  if (!r.ok) throw new Error('删除失败');
}

export interface SessionItem { id: string; title: string; mode: string; summary?: string; created_at: string; updated_at: string; }
export interface ChatMessage { id: string; session_id: string; role: string; content: string; mode: string; result_summary?: string; created_at: string; }
export interface SessionDetail { session: SessionItem; messages: ChatMessage[]; memorySummary: Record<string, unknown>; }
export interface MessageResponse {
  sessionId: string; userMessage: ChatMessage;
  assistantMessage: Record<string, unknown> & { content: string; confidence: number; abstained: boolean; usedLLM: boolean; };
  evidence: Record<string,unknown>[]; confidence: number; abstained: boolean; warnings: string[];
}

export const chatApi = {
  createSession: (mode = 'react') => apiPost<{ sessionId: string; title: string }>('/chat/sessions', { mode }),
  listSessions: (limit = 30) => apiGet<{ sessions: SessionItem[] }>(`/chat/sessions?limit=${limit}`).then(d => d.sessions),
  getSession: (id: string) => apiGet<SessionDetail>(`/chat/sessions/${id}`),
  deleteSession: (id: string) => apiDelete(`/chat/sessions/${id}`),
  sendMessage: (sessionId: string, content: string, mode = 'react') =>
    apiPost<MessageResponse>(`/chat/sessions/${sessionId}/messages`, { content, mode }),
};
