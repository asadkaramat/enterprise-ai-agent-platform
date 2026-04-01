import { apiClient } from './client';
import type { Tool, ToolCreate } from '../types';

type PaginatedResponse = { items: Tool[]; total: number };

export async function fetchTools(): Promise<Tool[]> {
  const { data } = await apiClient.get<PaginatedResponse | Tool[]>('/api/tools');
  return Array.isArray(data) ? data : (data as PaginatedResponse).items ?? [];
}

export async function fetchTool(id: string): Promise<Tool> {
  const { data } = await apiClient.get<Tool>(`/api/tools/${id}`);
  return data;
}

export async function createTool(payload: ToolCreate): Promise<Tool> {
  const { data } = await apiClient.post<Tool>('/api/tools', payload);
  return data;
}

export async function updateTool(id: string, payload: Partial<ToolCreate>): Promise<Tool> {
  const { data } = await apiClient.put<Tool>(`/api/tools/${id}`, payload);
  return data;
}

export async function deleteTool(id: string): Promise<void> {
  await apiClient.delete(`/api/tools/${id}`);
}
