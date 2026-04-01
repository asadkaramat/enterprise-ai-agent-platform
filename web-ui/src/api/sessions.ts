import { apiClient } from './client';
import type { Session, Message } from '../types';

// Normalize backend session shape → frontend Session type
// Backend returns session_id / token_count; frontend expects id / total_tokens
function normalizeSession(raw: Record<string, unknown>): Session {
  return {
    id: (raw.session_id ?? raw.id) as string,
    tenant_id: raw.tenant_id as string,
    agent_id: raw.agent_id as string,
    agent_name: raw.agent_name as string | undefined,
    status: raw.status as Session['status'],
    step_count: (raw.step_count ?? 0) as number,
    total_tokens: (raw.token_count ?? raw.total_tokens ?? 0) as number,
    created_at: raw.created_at as string,
    updated_at: (raw.updated_at ?? raw.created_at) as string,
    completed_at: raw.completed_at as string | undefined,
  };
}

export async function fetchSessions(status?: string): Promise<Session[]> {
  const params = status ? { status } : {};
  const { data } = await apiClient.get<Record<string, unknown>[]>('/api/sessions', { params });
  return data.map(normalizeSession);
}

export async function fetchSession(id: string): Promise<Session> {
  const { data } = await apiClient.get<Record<string, unknown>>(`/api/sessions/${id}`);
  return normalizeSession(data);
}

export async function fetchSessionMessages(id: string): Promise<Message[]> {
  // Messages are embedded in the session detail response
  const { data } = await apiClient.get<Record<string, unknown>>(`/api/sessions/${id}`);
  const msgs = (data.messages ?? []) as Array<Record<string, unknown>>;
  return msgs.map((m, i) => ({
    id: String(i),
    session_id: id,
    role: m.role as Message['role'],
    content: (m.content ?? '') as string,
    created_at: (data.created_at ?? '') as string,
  }));
}

export async function sendMessage(id: string, content: string): Promise<Message> {
  const { data } = await apiClient.post<Record<string, unknown>>(
    `/api/sessions/${id}/messages`,
    { message: content },
  );
  const session = normalizeSession(data);
  // Return the last assistant message from the updated session
  const msgs = (data.messages ?? []) as Array<Record<string, unknown>>;
  const last = msgs[msgs.length - 1] ?? {};
  return {
    id: String(msgs.length - 1),
    session_id: session.id,
    role: (last.role ?? 'assistant') as Message['role'],
    content: (last.content ?? '') as string,
    created_at: session.updated_at,
  };
}

export async function createSession(agentId: string, message: string): Promise<Session> {
  const { data } = await apiClient.post<Record<string, unknown>>('/api/sessions', {
    agent_id: agentId,
    message,
  });
  return normalizeSession(data);
}

export async function terminateSession(id: string): Promise<void> {
  await apiClient.post(`/api/sessions/${id}/terminate`);
}
