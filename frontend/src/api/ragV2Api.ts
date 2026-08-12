/**
 * RAG V2 API 客户端 — Phase 11
 *
 * snake_case → camelCase 转换在此层完成。
 * 所有请求通过 Vite 代理 /api → http://localhost:8000 路由到后端。
 */
import type {
  RagTrace,
  RagAnswer,
  RagV2Status,
  RagSearchResult,
} from "../types/ragV2";

const BASE = "/api/rag/v2";

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
      throw err;
    }
    throw { status: 0, detail: String(err) };
  }
  if (!resp.ok) {
    let detail: string = resp.statusText;
    try {
      const body = await resp.json();
      const d = (body as Record<string, unknown>).detail;
      if (typeof d === "string") detail = d;
    } catch {
      /* ignore */
    }
    throw { status: resp.status, detail };
  }
  const body = await resp.json();
  return normalizeKeys(body) as T;
}

function extractErrorDetail(err: unknown): string {
  if (err && typeof err === "object" && "detail" in err) {
    const d = (err as Record<string, unknown>).detail;
    return typeof d === "string" ? d : String(d);
  }
  return String(err);
}

// ================================================================
// Public API
// ================================================================

/** POST /rag/v2/search */
export async function ragV2Search(
  query: string,
  topK?: number,
  filters?: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<{ results: RagSearchResult[]; trace: RagTrace }> {
  const r = await fetch(`${BASE}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: topK ?? 10, filters }),
    signal,
  });
  if (!r.ok) {
    let detail: string = r.statusText;
    try {
      const b = await r.json();
      const d = (b as Record<string, unknown>).detail;
      if (typeof d === "string") detail = d;
    } catch { /* ignore */ }
    throw { status: r.status, detail };
  }
  const body = await r.json();
  return normalizeKeys(body) as { results: RagSearchResult[]; trace: RagTrace };
}

/** POST /rag/v2/ask */
export async function ragV2Ask(
  question: string,
  signal?: AbortSignal,
): Promise<RagAnswer> {
  const r = await fetch(`${BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, include_trace: true }),
    signal,
  });
  if (!r.ok) {
    let detail: string = r.statusText;
    try {
      const b = await r.json();
      const d = (b as Record<string, unknown>).detail;
      if (typeof d === "string") detail = d;
    } catch { /* ignore */ }
    throw { status: r.status, detail };
  }
  const body = await r.json();
  return normalizeKeys(body) as RagAnswer;
}

/** GET /rag/v2/status */
export async function ragV2Status(
  signal?: AbortSignal,
): Promise<RagV2Status> {
  return fetchJson<RagV2Status>(`${BASE}/status`, signal);
}

/** GET /rag/v2/traces/{traceId} */
export async function ragV2GetTrace(
  traceId: string,
  signal?: AbortSignal,
): Promise<RagTrace> {
  return fetchJson<RagTrace>(`${BASE}/traces/${encodeURIComponent(traceId)}`, signal);
}
