export interface Agent {
  id: string;
  tenant_id: string;
  name: string;
  description?: string;
  system_prompt: string;
  model: string;
  max_steps: number;
  token_budget: number;
  session_timeout: number;
  memory_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentCreate {
  name: string;
  description?: string;
  system_prompt: string;
  model: string;
  max_steps: number;
  token_budget: number;
  session_timeout: number;
  memory_enabled: boolean;
}

export type SessionStatus = 'active' | 'completed' | 'error' | 'terminated';

export interface Session {
  id: string;
  tenant_id: string;
  agent_id: string;
  agent_name?: string;
  status: SessionStatus;
  step_count: number;
  total_tokens: number;
  created_at: string;
  updated_at: string;
  completed_at?: string;
}

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool';

export interface Message {
  id: string;
  session_id: string;
  role: MessageRole;
  content: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  tool_result?: unknown;
  created_at: string;
  event_type?: string;
}

export interface Tool {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  version: string;
  endpoint_url: string;
  http_method: 'POST' | 'GET' | 'PUT';
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  auth_type: 'none' | 'api_key';
  auth_config?: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  is_cacheable?: boolean;
  cache_ttl_seconds?: number;
}

export interface ToolCreate {
  name: string;
  description: string;
  version: string;
  endpoint_url: string;
  http_method: 'POST' | 'GET' | 'PUT';
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  auth_type: 'none' | 'api_key';
  auth_config?: Record<string, unknown>;
  is_cacheable?: boolean;
  cache_ttl_seconds?: number;
}

export interface ToolBinding {
  tool_id: string;
  tool_name: string;
  is_authorized: boolean;
}

export interface UsageSummary {
  total_sessions: number;
  active_sessions: number;
  total_tokens: number;
  estimated_cost: number;
  daily_counts: Array<{ date: string; count: number }>;
}

export interface HealthResponse {
  status: string;
  version?: string;
}

export interface ApiError {
  detail: string;
}

export interface EgressEntry {
  id: string;
  tenant_id: string;
  endpoint_pattern: string;
  port: number;
  protocol: string;
  description?: string;
  is_active: boolean;
  created_at: string;
}

export interface Policy {
  id: string;
  tenant_id: string;
  name: string;
  scope: string;
  scope_ref_id?: string;
  policy_lang: string;
  policy_body: string;
  version: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
