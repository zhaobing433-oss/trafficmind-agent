/** 前端伪流式工具 — Phase20 R2：已删除 thinkingSteps（伪造思考步骤），只保留文本逐句输出 */

/**
 * 流式逐句输出文本。
 * 按句号/换行/逗号切分，每段有明确停顿。
 * 使用 requestAnimationFrame 保证 UI 实时更新。
 */
export async function streamText(
  msgId: string,
  fullText: string,
  onUpdate: (content: string) => void,
  delayMs = 30
): Promise<void> {
  if (!fullText) return;
  const segments = splitBySentences(fullText);

  let accumulated = '';
  for (const seg of segments) {
    accumulated += seg;
    onUpdate(accumulated);
    // Use rAF to force React to flush this render before proceeding
    await new Promise<void>(resolve => {
      requestAnimationFrame(() => {
        setTimeout(resolve, delayMs);
      });
    });
  }
}

/** 按语义边界切分文本：句号、换行、逗号、问号 */
function splitBySentences(text: string): string[] {
  const result: string[] = [];
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    // Break at these natural boundaries, and include the boundary char in current segment
    if (ch === '。' || ch === '\n' || ch === '？' || ch === '！' || ch === '，' || ch === '；') {
      result.push(text.slice(start, i + 1));
      start = i + 1;
    }
  }
  // Remaining text
  if (start < text.length) {
    result.push(text.slice(start));
  }
  // If too few segments, split further
  if (result.length <= 2 && text.length > 20) {
    const refined: string[] = [];
    for (const seg of result) {
      if (seg.length > 15) {
        // split every 8-15 chars for long segments
        for (let j = 0; j < seg.length; j += 12) {
          refined.push(seg.slice(j, j + 12));
        }
      } else {
        refined.push(seg);
      }
    }
    return refined;
  }
  return result;
}
