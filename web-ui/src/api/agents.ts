import { apiClient } from './client';
import type { Agent, AgentCreate, ToolBinding } from '../types';

// Normalize backend agent shape → frontend Agent type
function normalizeAgent(raw: Record<string, unknown>): Agent {
  return {
    id: raw.id as string,
    tenant_id: raw.tenant_id as string,
    name: raw.name as string,
    description: raw.description as string | undefined,
    system_prompt: raw.system_prompt as string,
    model: raw.model as string,
    max_steps: (raw.max_steps ?? 10) as number,
    token_budget: (raw.token_budget ?? 4096) as number,
    // backend uses session_timeout_seconds, frontend type uses session_timeout
    session_timeout: (raw.session_timeout_seconds ?? raw.session_timeout ?? 300) as number,
    memory_enabled: (raw.memory_enabled ?? false) as boolean,
    created_at: raw.created_at as string,
    updated_at: raw.updated_at as string,
  };
}

type PaginatedResponse = { items: Record<string, unknown>[]; total: number };

export async function fetchAgents(): Promise<Agent[]> {
  const { data } = await apiClient.get<PaginatedResponse | Record<string, unknown>[]>('/api/agents');
  const items = Array.isArray(data) ? data : (data as PaginatedResponse).items ?? [];
  return items.map(normalizeAgent);
}

export async function fetchAgent(id: string): Promise<Agent> {
  const { data } = await apiClient.get<Record<string, unknown>>(`/api/agents/${id}`);
  return normalizeAgent(data);
}

export async function createAgent(payload: AgentCreate): Promise<Agent> {
  // Map session_timeout → session_timeout_seconds for the backend
  const backendPayload = { ...payload, session_timeout_seconds: payload.session_timeout };
  const { data } = await apiClient.post<Record<string, unknown>>('/api/agents', backendPayload);
  return normalizeAgent(data);
}

export async function updateAgent(id: string, payload: Partial<AgentCreate>): Promise<Agent> {
  const backendPayload = { ...payload, session_timeout_seconds: payload.session_timeout };
  const { data } = await apiClient.put<Record<string, unknown>>(`/api/agents/${id}`, backendPayload);
  return normalizeAgent(data);
}

export async function deleteAgent(id: string): Promise<void> {
  await apiClient.delete(`/api/agents/${id}`);
}

export async function fetchAgentTools(agentId: string): Promise<ToolBinding[]> {
  const { data } = await apiClient.get<ToolBinding[]>(`/api/agents/${agentId}/tools`);
  return Array.isArray(data) ? data : [];
}

export async function bindTool(agentId: string, toolId: string): Promise<void> {
  await apiClient.post(`/api/agents/${agentId}/tools/${toolId}`);
}

export async function unbindTool(agentId: string, toolId: string): Promise<void> {
  await apiClient.delete(`/api/agents/${agentId}/tools/${toolId}`);
}

export async function setToolAuthorization(
  agentId: string,
  toolId: string,
  authorized: boolean
): Promise<void> {
  await apiClient.patch(`/api/agents/${agentId}/tools/${toolId}`, { is_authorized: authorized });
}
