import type { RunListItem } from '../api/collaborationApi';
import type { SessionItem } from '../api/chatApi';

export interface RecentJudgment {
  eventId: string;
  businessTitle: string;
  lastJudgedAt: string;
  judgmentLoaded: number;
  latestSessionId: string;
  latestRunId: string;
  latestStatus: string;
}

export interface SessionJudgments { session: SessionItem; runs: RunListItem[]; error?: string }
export interface RecentJudgments {
  events: RecentJudgment[];
  legacy: (SessionItem & { unboundRunId?: string })[];
  failedSessions: SessionItem[];
  sessionsLoaded: number;
  runsLoaded: number;
}

export type GroundingBlockStatus = 'READY' | 'EMPTY' | 'UNAVAILABLE' | 'UNRESOLVED' | 'ERROR' | 'NOT_RECORDED';
export interface GroundingRow {
  title: string;
  summary: string;
  metadata: string[];
  sourceLabel: string;
  documentId?: string;
  outcome?: string;
}
export interface GroundingBlock {
  kind: 'regional' | 'history' | 'knowledge' | 'case';
  title: string;
  status: GroundingBlockStatus;
  message: string;
  metadata: string[];
  rows: GroundingRow[];
}
export interface GroundingPresentation {
  recorded: boolean;
  invalid: boolean;
  assembledAt: string;
  blocks: GroundingBlock[];
  availableRefCount: number;
  outputRefCount: number;
  outputRefLabels: string[];
  usageUnverified: boolean;
  auditRecorded: boolean;
  inputFactCount: number;
  inputRefCount: number;
}
