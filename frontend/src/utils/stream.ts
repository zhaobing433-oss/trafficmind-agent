/** 前端伪流式工具 */

export function thinkingSteps(): string {
  const steps = ['🔍 正在分析问题...', '📚 检索知识库中...', '🤔 综合评估...', '✍ 生成回答...'];
  return steps[Math.floor(Math.random() * steps.length)];
}

export async function streamText(
  msgId: string,
  fullText: string,
  onUpdate: (content: string) => void,
  delay = 15
): Promise<void> {
  if (!fullText) return;
  const chunks = splitIntoChunks(fullText, 3);
  for (let i = 1; i <= chunks.length; i++) {
    onUpdate(chunks.slice(0, i).join(''));
    await sleep(delay);
  }
}

function splitIntoChunks(text: string, charsPerChunk: number): string[] {
  const chunks: string[] = [];
  let i = 0;
  while (i < text.length) {
    let end = i + charsPerChunk;
    // Try to break at sentence boundary
    if (end < text.length) {
      const nextPeriod = text.indexOf('。', end);
      const nextNewline = text.indexOf('\n', end);
      const boundary = Math.min(nextPeriod > 0 ? nextPeriod + 1 : Infinity, nextNewline > 0 ? nextNewline + 1 : Infinity);
      if (boundary < end + 30) end = boundary;
    }
    chunks.push(text.slice(i, Math.min(end, text.length)));
    i = end;
  }
  return chunks;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
