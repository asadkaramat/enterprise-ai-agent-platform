import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Eye } from 'lucide-react';
import { fetchSessions } from '../api/sessions';
import StatusBadge from '../components/StatusBadge';
import LoadingSpinner from '../components/LoadingSpinner';
import type { SessionStatus } from '../types';

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'active', label: 'Active' },
  { value: 'completed', label: 'Completed' },
  { value: 'error', label: 'Error' },
  { value: 'terminated', label: 'Terminated' },
];

function truncId(id: string) {
  return id.slice(0, 8) + '…';
}

function fmtDate(s: string) {
  return new Date(s).toLocaleString();
}

function duration(created: string, completed?: string): string {
  const end = completed ? new Date(completed) : new Date();
  const ms = end.getTime() - new Date(created).getTime();
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  return `${mins}m ${secs % 60}s`;
}

export default function Sessions() {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState('');

  const { data: sessions = [], isLoading, error } = useQuery({
    queryKey: ['sessions', statusFilter],
    queryFn: () => fetchSessions(statusFilter || undefined),
    refetchInterval: 10_000, // auto-refresh every 10s
  });

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-200">
        Failed to load sessions.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">Sessions</h1>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

      <div className="rounded-xl bg-white shadow-sm ring-1 ring-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-100">
            <thead>
              <tr className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                <th className="px-6 py-3">Session ID</th>
                <th className="px-6 py-3">Agent</th>
                <th className="px-6 py-3">Status</th>
                <th className="px-6 py-3">Steps</th>
                <th className="px-6 py-3">Tokens</th>
                <th className="px-6 py-3">Duration</th>
                <th className="px-6 py-3">Created</th>
                <th className="px-6 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white text-sm text-gray-700">
              {sessions.length === 0 ? (
                <tr>
                  <td
                    colSpan={8}
                    className="px-6 py-12 text-center text-gray-400"
                  >
                    No sessions found.
                  </td>
                </tr>
              ) : (
                sessions.map((s) => (
                  <tr
                    key={s.id}
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() => navigate(`/sessions/${s.id}`)}
                  >
                    <td className="px-6 py-4 font-mono text-xs text-gray-600">
                      {truncId(s.id)}
                    </td>
                    <td className="px-6 py-4">{s.agent_name ?? s.agent_id}</td>
                    <td className="px-6 py-4">
                      <StatusBadge status={s.status as SessionStatus} />
                    </td>
                    <td className="px-6 py-4 text-gray-600">{s.step_count}</td>
                    <td className="px-6 py-4 text-gray-600">
                      {s.total_tokens.toLocaleString()}
                    </td>
                    <td className="px-6 py-4 text-gray-500">
                      {duration(s.created_at, s.completed_at)}
                    </td>
                    <td className="px-6 py-4 text-gray-500">
                      {fmtDate(s.created_at)}
                    </td>
                    <td
                      className="px-6 py-4"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        onClick={() => navigate(`/sessions/${s.id}`)}
                        className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-blue-600 transition-colors"
                        title="View session"
                      >
                        <Eye size={15} />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
