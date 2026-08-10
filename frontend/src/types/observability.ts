/** Phase 14 Observability Types */

export interface NodeObservation {
  node_id: string; node_type: string; display_name: string; description: string;
  status: string; attempt: number; max_attempts: number;
  started_at: string; completed_at: string; duration_ms: number;
  input_summary: Record<string, unknown>; output_summary: Record<string, unknown>;
  evidence_refs: string[]; tool_calls: Record<string, unknown>[]; error: string;
}

export interface AgentObservation {
  agent_name: string; summary: string; urgency: string;
  findings: string[]; proposed_actions: Record<string, unknown>[];
  evidence_refs: string[]; spatial_context_summary: Record<string, unknown>;
  tool_calls: Record<string, unknown>[];
}

export interface ApprovalObservation {
  approval_id: string; decision: string; reviewer: string; comment: string;
  created_at: string; decided_at: string;
  proposed_actions: Record<string, unknown>[]; edited_actions: Record<string, unknown>[];
}

export interface ActionObservation {
  action_id: string; action_type: string; status: string; idempotency_key: string;
  before_snapshot_summary: Record<string, unknown>; after_snapshot_summary: Record<string, unknown>;
  improvement: Record<string, unknown>;
}

export interface WorkflowObservability {
  run_id: string; definition_id: string; definition_name: string;
  status: string; started_at: string; completed_at: string; total_duration_ms: number;
  trigger_reason: string; current_node: string;
  nodes: NodeObservation[];
  agent: AgentObservation | null;
  approval: ApprovalObservation | null;
  actions: ActionObservation[];
  metrics: Record<string, unknown>;
  simulation_refs: Record<string, unknown>;
}
