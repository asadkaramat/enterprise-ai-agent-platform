import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Pencil, Trash2 } from 'lucide-react';
import { fetchTools, deleteTool } from '../api/tools';
import LoadingSpinner from '../components/LoadingSpinner';

export default function Tools() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const { data: tools = [], isLoading, error } = useQuery({
    queryKey: ['tools'],
    queryFn: fetchTools,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteTool,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tools'] });
      setConfirmDelete(null);
    },
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
        Failed to load tools.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">Tools</h1>
        <Link
          to="/tools/new"
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
        >
          <Plus size={16} />
          Register Tool
        </Link>
      </div>

      <div className="rounded-xl bg-white shadow-sm ring-1 ring-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-100">
            <thead>
              <tr className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                <th className="px-6 py-3">Name</th>
                <th className="px-6 py-3">Version</th>
                <th className="px-6 py-3">Method</th>
                <th className="px-6 py-3">Endpoint</th>
                <th className="px-6 py-3">Status</th>
                <th className="px-6 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white text-sm text-gray-700">
              {tools.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-gray-400">
                    No tools registered yet.{' '}
                    <Link to="/tools/new" className="text-blue-600 hover:underline">
                      Register your first tool
                    </Link>
                  </td>
                </tr>
              ) : (
                tools.map((tool) => (
                  <tr key={tool.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <p className="font-medium text-gray-900">{tool.name}</p>
                      <p className="text-xs text-gray-500 mt-0.5 line-clamp-1">
                        {tool.description}
                      </p>
                    </td>
                    <td className="px-6 py-4 font-mono text-xs text-gray-600">
                      {tool.version}
                    </td>
                    <td className="px-6 py-4">
                      <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-semibold text-purple-700">
                        {tool.http_method}
                      </span>
                    </td>
                    <td className="px-6 py-4 max-w-xs">
                      <span className="truncate block font-mono text-xs text-gray-500">
                        {tool.endpoint_url}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                          tool.is_active
                            ? 'bg-green-100 text-green-700'
                            : 'bg-gray-100 text-gray-500'
                        }`}
                      >
                        {tool.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => navigate(`/tools/${tool.id}/edit`)}
                          className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-blue-600 transition-colors"
                          title="Edit"
                        >
                          <Pencil size={15} />
                        </button>
                        <button
                          onClick={() => setConfirmDelete(tool.id)}
                          className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600 transition-colors"
                          title="Delete"
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Confirm delete dialog */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl space-y-4">
            <h2 className="text-base font-semibold text-gray-900">Delete Tool?</h2>
            <p className="text-sm text-gray-500">
              This action cannot be undone. Agents with this tool bound may be
              affected.
            </p>
            {deleteMutation.isError && (
              <p className="text-sm text-red-600">
                Failed to delete. Please try again.
              </p>
            )}
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setConfirmDelete(null)}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate(confirmDelete)}
                disabled={deleteMutation.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
