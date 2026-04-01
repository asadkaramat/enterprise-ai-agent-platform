import { useQuery } from '@tanstack/react-query';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Activity, Zap, DollarSign, BarChart3 } from 'lucide-react';
import MetricCard from '../components/MetricCard';
import StatusBadge from '../components/StatusBadge';
import LoadingSpinner from '../components/LoadingSpinner';
import { fetchUsageSummary } from '../api/audit';
import { fetchSessions } from '../api/sessions';
import type { SessionStatus } from '../types';

function fmt(n: number) {
  return n.toLocaleString();
}

function fmtCost(n: number) {
  return `$${n.toFixed(4)}`;
}

function fmtDate(s: string) {
  return new Date(s).toLocaleString();
}

function truncId(id: string) {
  return id.slice(0, 8) + '…';
}

export default function Dashboard() {
  const {
    data: summary,
    isLoading: sumLoading,
    error: sumError,
  } = useQuery({
    queryKey: ['usage-summary'],
    queryFn: fetchUsageSummary,
  });

  const {
    data: sessions,
    isLoading: sessLoading,
    error: sessError,
  } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => fetchSessions(),
  });

  if (sumLoading || sessLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  if (sumError || sessError) {
    return (
      <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-200">
        Failed to load dashboard data. Make sure the gateway is running and your API key is valid.
      </div>
    );
  }

  const recentSessions = (sessions ?? []).slice(0, 10);

  return (
    <div className="space-y-6">
      {/* Metric cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Total Sessions"
          value={fmt(summary?.total_sessions ?? 0)}
          icon={<BarChart3 size={20} />}
        />
        <MetricCard
          title="Active Sessions"
          value={fmt(summary?.active_sessions ?? 0)}
          icon={<Activity size={20} />}
          trend={(summary?.active_sessions ?? 0) > 0 ? 'Currently running' : 'None running'}
          trendUp={(summary?.active_sessions ?? 0) > 0}
        />
        <MetricCard
          title="Total Tokens"
          value={fmt(summary?.total_tokens ?? 0)}
          icon={<Zap size={20} />}
        />
        <MetricCard
          title="Estimated Cost"
          value={fmtCost(summary?.estimated_cost ?? 0)}
          icon={<DollarSign size={20} />}
        />
      </div>

      {/* Line chart */}
      <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200">
        <h2 className="mb-4 text-sm font-semibold text-gray-700">
          Sessions — Last 7 Days
        </h2>
        {summary?.daily_counts?.length ? (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart
              data={summary.daily_counts}
              margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="count"
                stroke="#2563eb"
                strokeWidth={2}
                dot={{ r: 4, fill: '#2563eb' }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="py-12 text-center text-sm text-gray-400">
            No session data available yet.
          </p>
        )}
      </div>

      {/* Recent sessions table */}
      <div className="rounded-xl bg-white shadow-sm ring-1 ring-gray-200">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-sm font-semibold text-gray-700">Recent Sessions</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-100">
            <thead>
              <tr className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                <th className="px-6 py-3">Session ID</th>
                <th className="px-6 py-3">Agent</th>
                <th className="px-6 py-3">Status</th>
                <th className="px-6 py-3">Tokens</th>
                <th className="px-6 py-3">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white text-sm text-gray-700">
              {recentSessions.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-10 text-center text-gray-400">
                    No sessions yet.
                  </td>
                </tr>
              ) : (
                recentSessions.map((s) => (
                  <tr key={s.id} className="hover:bg-gray-50">
                    <td className="px-6 py-3 font-mono text-xs text-gray-600">
                      {truncId(s.id)}
                    </td>
                    <td className="px-6 py-3">{s.agent_name ?? s.agent_id}</td>
                    <td className="px-6 py-3">
                      <StatusBadge status={s.status as SessionStatus} />
                    </td>
                    <td className="px-6 py-3">{fmt(s.total_tokens)}</td>
                    <td className="px-6 py-3 text-gray-500">{fmtDate(s.created_at)}</td>
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
