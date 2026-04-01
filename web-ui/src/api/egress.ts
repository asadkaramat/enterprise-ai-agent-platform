import { apiClient } from './client';
import type { EgressEntry } from '../types';

export interface EgressEntryCreate {
  endpoint_pattern: string;
  port: number;
  protocol: string;
  description?: string;
}

export async function fetchEgressEntries(): Promise<EgressEntry[]> {
  const { data } = await apiClient.get<EgressEntry[]>('/api/egress-allowlist');
  return data;
}

export async function createEgressEntry(
  payload: EgressEntryCreate
): Promise<EgressEntry> {
  const { data } = await apiClient.post<EgressEntry>(
    '/api/egress-allowlist',
    payload
  );
  return data;
}

export async function deleteEgressEntry(id: string): Promise<void> {
  await apiClient.delete(`/api/egress-allowlist/${id}`);
}
