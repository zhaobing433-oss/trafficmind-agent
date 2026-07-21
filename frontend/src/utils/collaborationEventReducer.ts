/**
 * SSE → CollaborationRun 状态归约器
 */
import type { CollaborationRun, CollaborationTask, CollaborationAgentResult, CollaborationConflict } from '../types/collaboration';

const initialState = (): CollaborationRun => ({
  runId: '', traceId: '', sessionId: '', status: 'created', executionEngine: 'orchestrator',
  protocolVersion: '1.0', selectedAgents: [], skippedAgents: [], routingReasons: [],
  tasks: [], agentResults: {}, conflicts: [], arbitrationResults: [],
  failedAgents: [], limitations: [], budgetUsage: { maxAgents: 6, maxAgentCalls: 2, maxRetries: 2, maxTotalSeconds: 120, usedAgentCalls: {}, usedRetries: {}, startedAt: '' },
  finalDecision: '', fusionSummary: '', requiresHumanReview: false, degraded: false,
  fallbackReason: '', startedAt: '', completedAt: '',
});

type Event = Record<string, unknown>;

type StoredState = CollaborationRun & { _lastSeq?: number };

export function reduceCollaborationEvent(state: CollaborationRun, event: Event): CollaborationRun {
  const evType = (event.eventType || event.type || '') as string;
  const seq = Number(event.sequenceNumber || 0);
  if (!evType) return state;
  const s = state as StoredState;
  if (seq > 0 && seq <= (s._lastSeq || 0)) return state;
  const updated = { ...state, _lastSeq: Math.max(seq, s._lastSeq || 0) } as StoredState;

  switch (evType) {
    case 'run_created':
      return { ...initialState(), runId: event.runId as string, traceId: event.traceId as string, sessionId: event.sessionId as string, startedAt: event.timestamp as string, status: 'created', selectedAgents: (event.selectedAgents as string[]) || [] } as CollaborationRun;

    case 'agent_route_done':
      return { ...state, selectedAgents: (event.selectedAgents as string[]) || state.selectedAgents, routingReasons: (event.routingReasons as string[]) || [], status: 'routing' };

    case 'task_graph_created': {
      const rawTasks = (event.tasks || (event.payload as Record<string,unknown>)?.tasks) as Record<string,unknown>[] | undefined;
      if (!rawTasks) return state;
      // normalizeEvent already converted snake_case→camelCase — read camelCase
      const tasks: CollaborationTask[] = rawTasks.map(t => ({
        taskId: String(t.taskId || t.task_id || ''),
        agentName: String(t.agentName || t.agent_name || ''),
        taskType: String(t.taskType || t.task_type || 'analyze'),
        status: 'pending' as const,
        dependsOn: (t.dependsOn || t.depends_on || []) as string[],
        priority: Number(t.priority || 5), attempt: Number(t.attempt || 0),
        maxRetries: Number(t.maxRetries || 1), timeoutSeconds: Number(t.timeoutSeconds || t.timeout_seconds || 30),
        error: String(t.error || ''),
      }));
      return { ...state, tasks, status: 'running' };
    }

    case 'task_started':
    case 'task_ready':
      return { ...state, tasks: state.tasks.map(t => t.taskId === event.taskId ? { ...t, status: 'running' as const, attempt: Number(event.attempt || t.attempt + 1) } : t) };

    case 'task_retrying':
      return { ...state, tasks: state.tasks.map(t => t.taskId === event.taskId ? { ...t, status: 'retrying' as const, attempt: Number(event.attempt || 1) } : t) };

    case 'task_succeeded':
      return { ...state, tasks: state.tasks.map(t => t.taskId === event.taskId ? { ...t, status: 'succeeded' as const } : t) };

    case 'task_failed':
      return { ...state, tasks: state.tasks.map(t => t.taskId === event.taskId ? { ...t, status: 'failed' as const, error: (event.error as string) || '' } : t) };

    case 'task_blocked':
      return { ...state, tasks: state.tasks.map(t => t.taskId === event.taskId ? { ...t, status: 'blocked' as const } : t) };

    case 'agent_result': {
      const an = (event.agentName || event.agent_name || '') as string;
      const result = (event.result || event.payload || event) as Record<string,unknown>;
      const findings = (result.findings || event.findings || []) as string[];
      const agentResult: CollaborationAgentResult = {
        agentName: an, role: (event.role as string) || '',
        status: 'completed', findings,
        confidence: Number(result.confidence || event.confidence || 0),
        suggestion: (result.suggestion || result.recommendation || event.suggestion || '') as string,
        urgency: (result.urgency || event.urgency || 'low') as string,
        evidenceRefs: (result.evidenceRefs || event.evidenceRefs || []) as string[],
        attempt: Number(event.attempt || 1), duration: Number(event.duration || 0),
      };
      return {
        ...state,
        agentResults: { ...state.agentResults, [an]: agentResult },
        tasks: state.tasks.map(t => t.agentName === an || (event.taskId && t.taskId === event.taskId) ? { ...t, status: 'succeeded' as const } : t),
      };
    }

    case 'conflict_detected': {
      const rawConflicts = (event.conflicts || (event.payload as Record<string,unknown>)?.conflicts || []) as Record<string,unknown>[];
      const conflicts: CollaborationConflict[] = rawConflicts.map(c => ({
        id: String(c.id || c.conflictId || c.conflict_id || ''),
        type: String(c.type || ''), description: String(c.description || ''),
        participants: (c.participants as string[]) || [],
        proposals: (c.proposals as Record<string,unknown>[]) || [],
        severity: String(c.severity || 'low'), status: String(c.status || 'open'),
        resolution: String(c.resolution || ''), resolvedBy: String(c.resolvedBy || c.resolved_by || ''),
        requiresHumanReview: Boolean(c.requiresHumanReview || c.requires_human_review),
      }));
      return { ...state, conflicts };
    }

    case 'conflict_check_done': {
      const conflicts = (event.conflicts || []) as CollaborationConflict[];
      return { ...state, conflicts, status: 'arbitrating' };
    }

    case 'arbitration_result':
      return { ...state, arbitrationResults: [...state.arbitrationResults, event as unknown as Record<string,unknown>] };

    case 'fusion_start':
      return { ...state, status: 'fusing' };

    case 'fusion_delta':
      return { ...state, fusionSummary: state.fusionSummary + ((event.text as string) || '') };

    case 'fusion_done':
      return { ...state, status: 'completed', fusionSummary: (event.fusionSummary as string) || state.fusionSummary };

    case 'run_completed':
      return { ...state, status: 'completed', completedAt: event.timestamp as string };

    case 'run_partial_success':
      return { ...state, status: 'partial_success', completedAt: event.timestamp as string, limitations: (event.reason as string) ? [event.reason as string] : state.limitations };

    case 'run_failed':
      return { ...state, status: 'failed', completedAt: event.timestamp as string };

    case 'run_requires_human_review':
      return { ...state, status: 'requires_human_review', requiresHumanReview: true };

    case 'run_interrupted':
      return { ...state, status: 'interrupted', completedAt: event.timestamp as string };

    case 'fallback_started':
      return { ...state, degraded: true, fallbackReason: (event.reason as string) || '', executionEngine: 'legacy' };

    case 'budget_updated':
      return { ...state, budgetUsage: (event.payload || event) as unknown as CollaborationRun['budgetUsage'] };

    case 'done':
      return {
        ...state,
        status: (state.status !== 'running') ? state.status : 'completed',
        completedAt: event.timestamp as string,
        executionEngine: (event.executionEngine as 'orchestrator' | 'legacy') || state.executionEngine,
        fusionSummary: (event.fusionSummary as string) || state.fusionSummary,
        finalDecision: (event.finalDecision as string) || state.finalDecision,
        budgetUsage: (event.budgetUsage as CollaborationRun['budgetUsage']) || state.budgetUsage,
        agentResults: { ...state.agentResults, ...(event.agentResults as Record<string, CollaborationAgentResult> || {}) },
        // NEVER overwrite tasks from done — task lifecycle events are authoritative
      };
  }
  return state;
}
