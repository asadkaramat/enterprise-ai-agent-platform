import { apiClient } from './client';
import type { UsageSummary, HealthResponse } from '../types';

export async function fetchUsageSummary(): Promise<UsageSummary> {
  const { data } = await apiClient.get<Record<string, unknown>>('/api/audit/usage/summary');
  // Normalize backend field names → frontend type
  return {
    total_sessions: (data.total_sessions ?? 0) as number,
    active_sessions: (data.active_sessions ?? 0) as number,
    total_tokens: (data.total_tokens ?? 0) as number,
    estimated_cost: (data.estimated_cost_usd ?? data.estimated_cost ?? 0) as number,
    daily_counts: (data.daily_counts ?? []) as Array<{ date: string; count: number }>,
  };
}

export async function checkHealth(): Promise<HealthResponse> {
  const { data } = await apiClient.get<HealthResponse>('/health');
  return data;
}
