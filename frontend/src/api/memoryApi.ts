/**
 * Memory V2 API 客户端 — Phase 10
 *
 * snake_case → camelCase 转换在此层完成。
 * 组件只接收 camelCase 数据。
 */

import type {
  MemorySessionView,
  MemoryTraceResponse,
  MemoryItem,
  MemoryEventThread,
  MemorySelectedItem,
  MemoryRejectedItem,
  AgentMemoryInjection,
  MemoryWriteResult,
} from "../types/memory";

const BASE = "/memory";

function toCamel(s: string): string {
  return s.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}

function normalizeKeys(obj: unknown): unknown {
  if (Array.isArray(obj)) return obj.map(normalizeKeys);
  if (obj === null || typeof obj !== "object") return obj;
  const result: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    result[toCamel(k)] = normalizeKeys(v);
  }
  return result;
}

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(url, { signal });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw {
      status: resp.status,
      safeMessage: resp.status === 404 ? "请求的资源不存在" : `服务错误 (${resp.status})`,
      detail: text,
    };
  }
  const raw = await resp.json();
  return normalizeKeys(raw) as T;
}

// ================================================================
// Public API
// ================================================================

export async function getSessionMemory(
  sessionId: string,
  signal?: AbortSignal,
): Promise<MemorySessionView> {
  return fetchJson<MemorySessionView>(`${BASE}/sessions/${sessionId}`, signal);
}

export async function getRunMemoryTrace(
  runId: string,
  signal?: AbortSignal,
): Promise<MemoryTraceResponse> {
  return fetchJson<MemoryTraceResponse>(`${BASE}/runs/${runId}/trace`, signal);
}

export async function getMemoryItem(
  memoryId: string,
  signal?: AbortSignal,
): Promise<{ item: MemoryItem; supersedes: MemoryItem | null; eventThread: MemoryEventThread | null }> {
  return fetchJson(`${BASE}/items/${memoryId}`, signal);
}

export async function listEventThreads(
  sessionId: string,
  signal?: AbortSignal,
): Promise<{ sessionId: string; threads: MemoryEventThread[] }> {
  return fetchJson(`${BASE}/sessions/${sessionId}/threads`, signal);
}
