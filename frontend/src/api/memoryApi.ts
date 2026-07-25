/**
 * Memory V2 API 客户端 — Phase 10
 *
 * snake_case → camelCase 转换在此层完成。
 * 所有请求通过 Vite 代理 /api → http://localhost:8000 路由到后端。
 */

import type {
  MemorySessionView,
  MemoryTraceResponse,
  MemoryItem,
  MemoryEventThread,
} from "../types/memory";

const BASE = "/api/memory";

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
  let resp: Response;
  try {
    resp = await fetch(url, { signal });
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw err; // 正常取消，向上传递
    }
    throw {
      status: 0,
      safeMessage: "无法连接Memory API，请确认后端8000端口已启动",
      detail: String(err),
    };
  }

  if (!resp.ok) {
    const contentType = resp.headers.get("content-type") || "";
    const text = await resp.text().catch(() => "");
    // Vite dev server returns HTML when route doesn't match proxy
    if (contentType.includes("text/html") || text.trimStart().startsWith("<!DOCTYPE")) {
      throw {
        status: resp.status,
        safeMessage: "Memory API返回了非JSON响应，请检查前端代理配置",
        detail: text.slice(0, 200),
      };
    }
    throw {
      status: resp.status,
      safeMessage: resp.status === 404 ? "请求的资源不存在" : `服务错误 (${resp.status})`,
      detail: text.slice(0, 500),
    };
  }

  const raw = await resp.json();
  return normalizeKeys(raw) as T;
}

function enc(v: string): string {
  return encodeURIComponent(v);
}

// ================================================================
// Public API
// ================================================================

export async function getSessionMemory(
  sessionId: string,
  signal?: AbortSignal,
): Promise<MemorySessionView> {
  return fetchJson<MemorySessionView>(`${BASE}/sessions/${enc(sessionId)}`, signal);
}

export async function getRunMemoryTrace(
  runId: string,
  signal?: AbortSignal,
): Promise<MemoryTraceResponse> {
  return fetchJson<MemoryTraceResponse>(`${BASE}/runs/${enc(runId)}/trace`, signal);
}

export async function getMemoryItem(
  memoryId: string,
  signal?: AbortSignal,
): Promise<{ item: MemoryItem; supersedes: MemoryItem | null; eventThread: MemoryEventThread | null }> {
  return fetchJson(`${BASE}/items/${enc(memoryId)}`, signal);
}

export async function listEventThreads(
  sessionId: string,
  signal?: AbortSignal,
): Promise<{ sessionId: string; threads: MemoryEventThread[] }> {
  return fetchJson(`${BASE}/sessions/${enc(sessionId)}/threads`, signal);
}
