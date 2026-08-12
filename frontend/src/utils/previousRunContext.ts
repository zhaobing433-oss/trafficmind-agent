/**
 * previousRunContext 展示工具 — Phase 10
 *
 * 处理多层 JSON 编码的安全解析，最多 3 层，禁止无限递归。
 */

type JsonPrimitive = string | number | boolean | null;
type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

/**
 * 安全多层 JSON 解析。
 *
 * @param value  输入值（字符串、对象、null/undefined）
 * @param maxDepth  最大递归深度，默认 3
 * @returns  解析后的原始值（对象、数组、字符串或 null）
 */
export function parseNestedJson(value: unknown, maxDepth = 3): JsonValue {
  if (maxDepth <= 0) return safeString(value);
  if (value === null || value === undefined) return "";
  if (typeof value !== "string") {
    // Already an object/array — check if any string field is embedded JSON
    if (typeof value === "object" && !Array.isArray(value)) {
      return value as JsonValue;
    }
    return safeString(value);
  }

  const trimmed = value.trim();
  if (!trimmed) return "";

  // Try JSON parse
  try {
    const parsed = JSON.parse(trimmed);
    if (typeof parsed === "string") {
      // Parsed to a string — try one more level
      return parseNestedJson(parsed, maxDepth - 1);
    }
    if (typeof parsed === "object" && parsed !== null) {
      return parsed as JsonValue;
    }
    return safeString(parsed);
  } catch {
    // Not valid JSON — return as plain text
    return trimmed;
  }
}

/**
 * 从 previousRunContext 提取可展示的中文摘要。
 *
 * 优先级：fusionSummary > finalDecision > summary > text > 原始字符串
 */
export function extractPreviousRunSummary(rawValue: unknown): string {
  const parsed = parseNestedJson(rawValue);

  if (typeof parsed === "string") {
    return parsed.slice(0, 300);
  }

  if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
    const obj = parsed as Record<string, unknown>;

    // Priority 1: fusionSummary
    const fusion = obj.fusionSummary;
    if (typeof fusion === "string" && fusion.trim()) {
      return fusion.trim().slice(0, 300);
    }
    if (typeof fusion === "object" && fusion !== null) {
      const inner = (fusion as Record<string, unknown>).fusionSummary;
      if (typeof inner === "string" && inner.trim()) return inner.trim().slice(0, 300);
    }

    // Priority 2: finalDecision
    const fd = obj.finalDecision;
    if (typeof fd === "string" && fd.trim()) return fd.trim().slice(0, 300);
    if (typeof fd === "object" && fd !== null) {
      const inner = (fd as Record<string, unknown>).fusionSummary || (fd as Record<string, unknown>).summary;
      if (typeof inner === "string" && inner.trim()) return inner.trim().slice(0, 300);
    }

    // Priority 3: summary
    const sum = obj.summary;
    if (typeof sum === "string" && sum.trim()) return sum.trim().slice(0, 300);

    // Priority 4: text / content
    const text = obj.text || obj.content;
    if (typeof text === "string" && text.trim()) return text.trim().slice(0, 300);

    // Fallback: exclude internal metadata keys, show remaining content
    const excluded = new Set(["generationMode", "requiresHumanReview", "confidence",
      "actionPlan", "monitoringIndicators", "limitations", "arbitration", "mode"]);
    const remaining = Object.entries(obj)
      .filter(([k]) => !excluded.has(k))
      .map(([, v]) => (typeof v === "string" ? v : ""))
      .filter(Boolean)
      .join(" ");
    return remaining.slice(0, 300) || "(无文本摘要)";
  }

  return safeString(rawValue).slice(0, 300);
}

function safeString(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "object") {
    try { return JSON.stringify(v); } catch { return ""; }
  }
  return String(v);
}
