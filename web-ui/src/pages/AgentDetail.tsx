import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Pencil, Trash2, Plus, Play } from 'lucide-react';
import {
  fetchAgent,
  fetchAgentTools,
  bindTool,
  unbindTool,
  setToolAuthorization,
} from '../api/agents';
import { fetchTools } from '../api/tools';
import { createSession } from '../api/sessions';
import LoadingSpinner from '../components/LoadingSpinner';

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [selectedToolId, setSelectedToolId] = useState('');
  const [testMsg, setTestMsg] = useState('');
  const [showTestModal, setShowTestModal] = useState(false);

  const { data: agent, isLoading: agentLoading } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => fetchAgent(id!),
  });

  const { data: boundTools = [] } = useQuery({
    queryKey: ['agent-tools', id],
    queryFn: () => fetchAgentTools(id!),
  });

  const { data: allTools = [] } = useQuery({
    queryKey: ['tools'],
    queryFn: fetchTools,
  });

  const bindMutation = useMutation({
    mutationFn: () => bindTool(id!, selectedToolId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-tools', id] });
      setSelectedToolId('');
    },
  });

  const unbindMutation = useMutation({
    mutationFn: (toolId: string) => unbindTool(id!, toolId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-tools', id] }),
  });

  const authMutation = useMutation({
    mutationFn: ({ toolId, auth }: { toolId: string; auth: boolean }) =>
      setToolAuthorization(id!, toolId, auth),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-tools', id] }),
  });

  const sessionMutation = useMutation({
    mutationFn: () => createSession(id!, testMsg),
    onSuccess: (session) => navigate(`/sessions/${session.id}`),
  });

  const unboundTools = allTools.filter(
    (t) => !boundTools.find((b) => b.tool_id === t.id)
  );

  if (agentLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  if (!agent) {
    return (
      <p className="text-sm text-red-600">Agent not found.</p>
    );
  }

  const infoRows: [string, string][] = [
    ['Model', agent.model],
    ['Max Steps', String(agent.max_steps)],
    ['Token Budget', agent.token_budget.toLocaleString()],
    ['Session Timeout', `${agent.session_timeout}s`],
    ['Memory', agent.memory_enabled ? 'Enabled' : 'Disabled'],
    ['Created', new Date(agent.created_at).toLocaleDateString()],
  ];

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{agent.name}</h1>
          {agent.description && (
            <p className="mt-1 text-sm text-gray-500">{agent.description}</p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowTestModal(true)}
            className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 transition-colors"
          >
            <Play size={15} />
            Test Session
          </button>
          <button
            onClick={() => navigate(`/agents/${id}/edit`)}
            className="flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            <Pencil size={15} />
            Edit
          </button>
        </div>
      </div>

      {/* Config card */}
      <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200 space-y-4">
        <h2 className="text-sm font-semibold text-gray-700">Configuration</h2>
        <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 text-sm">
          {infoRows.map(([k, v]) => (
            <div key={k}>
              <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
                {k}
              </p>
              <p className="mt-0.5 font-medium text-gray-900">{v}</p>
            </div>
          ))}
        </div>
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-gray-400">
            System Prompt
          </p>
          <pre className="overflow-auto rounded-lg bg-gray-50 p-3 text-xs text-gray-700 font-mono whitespace-pre-wrap max-h-48 ring-1 ring-gray-200">
            {agent.system_prompt}
          </pre>
        </div>
      </div>

      {/* Bound tools */}
      <div className="rounded-xl bg-white shadow-sm ring-1 ring-gray-200">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-sm font-semibold text-gray-700">Bound Tools</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-100">
            <thead>
              <tr className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                <th className="px-6 py-3">Tool Name</th>
                <th className="px-6 py-3">Authorized</th>
                <th className="px-6 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white text-sm">
              {boundTools.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-6 py-8 text-center text-gray-400">
                    No tools bound to this agent.
                  </td>
                </tr>
              ) : (
                boundTools.map((bt) => (
                  <tr key={bt.tool_id}>
                    <td className="px-6 py-3 font-medium text-gray-900">
                      {bt.tool_name}
                    </td>
                    <td className="px-6 py-3">
                      <button
                        onClick={() =>
                          authMutation.mutate({
                            toolId: bt.tool_id,
                            auth: !bt.is_authorized,
                          })
                        }
                        className={`relative inline-flex h-5 w-9 rounded-full transition-colors focus:outline-none ${
                          bt.is_authorized ? 'bg-blue-600' : 'bg-gray-300'
                        }`}
                        role="switch"
                        aria-checked={bt.is_authorized}
                      >
                        <span
                          className={`inline-block h-4 w-4 translate-y-0.5 rounded-full bg-white shadow transition-transform ${
                            bt.is_authorized ? 'translate-x-4' : 'translate-x-0.5'
                          }`}
                        />
                      </button>
                    </td>
                    <td className="px-6 py-3">
                      <button
                        onClick={() => unbindMutation.mutate(bt.tool_id)}
                        disabled={unbindMutation.isPending}
                        className="flex items-center gap-1 text-xs text-red-500 hover:text-red-700 disabled:opacity-50 transition-colors"
                      >
                        <Trash2 size={13} />
                        Unbind
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Bind new tool row */}
        {unboundTools.length > 0 && (
          <div className="border-t border-gray-100 px-6 py-4 flex items-center gap-3">
            <select
              value={selectedToolId}
              onChange={(e) => setSelectedToolId(e.target.value)}
              className="flex-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">Select a tool to bind…</option>
              {unboundTools.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} (v{t.version})
                </option>
              ))}
            </select>
            <button
              onClick={() => bindMutation.mutate()}
              disabled={!selectedToolId || bindMutation.isPending}
              className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              <Plus size={14} />
              {bindMutation.isPending ? 'Binding…' : 'Bind Tool'}
            </button>
          </div>
        )}
      </div>

      {/* Test session modal */}
      {showTestModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl space-y-4">
            <h2 className="text-base font-semibold text-gray-900">
              Start Test Session
            </h2>
            <p className="text-sm text-gray-500">
              Send an initial message to start a new session with{' '}
              <span className="font-medium text-gray-700">{agent.name}</span>.
            </p>
            <textarea
              rows={3}
              value={testMsg}
              onChange={(e) => setTestMsg(e.target.value)}
              placeholder="Enter your first message…"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
              autoFocus
            />
            {sessionMutation.isError && (
              <p className="text-sm text-red-600">
                Failed to start session. Please try again.
              </p>
            )}
            <div className="flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowTestModal(false);
                  setTestMsg('');
                }}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => sessionMutation.mutate()}
                disabled={!testMsg.trim() || sessionMutation.isPending}
                className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
              >
                {sessionMutation.isPending ? 'Starting…' : 'Start Session'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
