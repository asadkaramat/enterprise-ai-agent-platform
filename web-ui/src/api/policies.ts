import { apiClient } from './client';
import type { Policy } from '../types';

export interface PolicyCreate {
  name: string;
  scope: string;
  scope_ref_id?: string;
  policy_lang: string;
  policy_body: string;
}

export interface PolicyUpdate {
  policy_body?: string;
  enabled?: boolean;
}

export async function fetchPolicies(): Promise<Policy[]> {
  const { data } = await apiClient.get<Policy[]>('/api/policies');
  return data;
}

export async function createPolicy(payload: PolicyCreate): Promise<Policy> {
  const { data } = await apiClient.post<Policy>('/api/policies', payload);
  return data;
}

export async function updatePolicy(
  id: string,
  payload: PolicyUpdate
): Promise<Policy> {
  const { data } = await apiClient.put<Policy>(`/api/policies/${id}`, payload);
  return data;
}

export async function deletePolicy(id: string): Promise<void> {
  await apiClient.delete(`/api/policies/${id}`);
}
