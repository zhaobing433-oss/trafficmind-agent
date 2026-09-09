import { record, text } from './judgment';

export interface JudgmentSelection { sessionId: string; runId: string; eventId?: string | null }

export function validateJudgmentDetail(detail: Record<string, unknown>, selection: JudgmentSelection): void {
  const run = record(detail.run);
  if (text(run.run_id) !== selection.runId || text(run.session_id) !== selection.sessionId) {
    throw new Error('研判与所选会话不匹配，未显示其它研判');
  }
  if (selection.eventId && text(record(run.normalized_event).eventId) !== selection.eventId) {
    throw new Error('研判与所选事件不匹配，未显示其它研判');
  }
}

// Cleanup invalidates both success and error, including late non-abortable responses.
export function loadJudgmentSelection(
  selection: JudgmentSelection,
  get: (id: string) => Promise<Record<string, unknown>>,
  receive: (detail: Record<string, unknown>) => void,
  fail: (message: string) => void,
): () => void {
  let active = true;
  get(selection.runId).then(detail => {
    if (!active) return;
    validateJudgmentDetail(detail, selection);
    receive(detail);
  }).catch(error => { if (active) fail(error instanceof Error ? error.message : '研判详情加载失败'); });
  return () => { active = false; };
}
