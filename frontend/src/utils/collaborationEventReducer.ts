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
      return {
        ...initialState(),
        runId: event.runId as string, traceId: event.traceId as string,
        sessionId: (event.sessionId || event.session_id || '') as string,
        startedAt: event.timestamp as string, status: 'created',
        selectedAgents: (event.selectedAgents as string[]) || [],
        userQuery: (event.userQuery as string) || '',
        contextPolicy: (event.contextPolicy as string) || 'fresh_event',
        fieldSources: (event.fieldSources as Record<string, string>) || {},
        previousRunContext: (event.previousRunContext && typeof event.previousRunContext === 'object' && (event.previousRunContext as Record<string,unknown>).runId)
          ? {
              runId: String((event.previousRunContext as Record<string,unknown>).runId || ''),
              summary: String((event.previousRunContext as Record<string,unknown>).summary || ''),
              status: String((event.previousRunContext as Record<string,unknown>).status || ''),
              event: ((event.previousRunContext as Record<string,unknown>).event || {}) as Record<string, unknown>,
              updatedAt: String((event.previousRunContext as Record<string,unknown>).updatedAt || ''),
            } as CollaborationRun['previousRunContext']
          : null,
      } as CollaborationRun;

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
    case 'task_ready': {
      const tid = (event.taskId || '') as string;
      const exists = state.tasks.some(t => t.taskId === tid);
      if (!exists && tid) {
        // Dynamic task insertion (e.g. ConflictArbiter added after task_graph_created)
        const newTask: CollaborationTask = {
          taskId: tid,
          agentName: (event.agentName || '') as string,
          taskType: 'arbitrate',
          status: 'running' as const,
          dependsOn: (event.dependsOn || []) as string[],
          priority: 5, attempt: Number(event.attempt || 1),
          maxRetries: 1, timeoutSeconds: 30, error: '',
        };
        return { ...state, tasks: [...state.tasks, newTask] };
      }
      return {
        ...state,
        tasks: state.tasks.map(t => t.taskId === tid
          ? { ...t, status: 'running' as const, attempt: Number(event.attempt || t.attempt + 1) }
          : t),
      };
    }

    case 'task_retrying':
      return { ...state, tasks: state.tasks.map(t => t.taskId === (event.taskId as string || '') ? { ...t, status: 'retrying' as const, attempt: Number(event.attempt || 1) } : t) };

    case 'task_succeeded':
      return { ...state, tasks: state.tasks.map(t => t.taskId === (event.taskId as string || '') ? { ...t, status: 'succeeded' as const } : t) };

    case 'task_failed':
      return { ...state, tasks: state.tasks.map(t => t.taskId === (event.taskId as string || '') ? { ...t, status: 'failed' as const, error: (event.error as string) || '' } : t) };

    case 'task_blocked':
      return { ...state, tasks: state.tasks.map(t => t.taskId === (event.taskId as string || '') ? { ...t, status: 'blocked' as const } : t) };

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
      const rawConflicts = (Array.isArray(event.conflicts) ? event.conflicts : []) as Record<string,unknown>[];
      const conflicts: CollaborationConflict[] = rawConflicts.map((c, i) => ({
        id: String(c.id || `conflict_${i}`),
        type: String(c.type || ''),
        description: String(c.description || ''),
        // Backend uses "agents" — normalize to "participants"
        participants: (Array.isArray(c.participants) ? c.participants
          : Array.isArray(c.agents) ? c.agents
          : []) as string[],
        proposals: (Array.isArray(c.proposals) ? c.proposals : []) as Record<string,unknown>[],
        severity: String(c.severity || 'low'),
        status: String(c.status || 'open'),
        resolution: String(c.resolution || ''),
        resolvedBy: String(c.resolvedBy || c.resolved_by || ''),
        requiresHumanReview: Boolean(c.requiresHumanReview || c.requires_human_review),
      }));
      return { ...state, conflicts, status: 'arbitrating' };
    }

    case 'arbitration_result': {
      const safeArbitrationResults = Array.isArray(state.arbitrationResults) ? state.arbitrationResults : [];
      return { ...state, arbitrationResults: [...safeArbitrationResults, event as unknown as Record<string,unknown>] };
    }

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
