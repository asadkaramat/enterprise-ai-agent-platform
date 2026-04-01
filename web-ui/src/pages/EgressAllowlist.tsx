import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { Trash2, Plus } from 'lucide-react';
import {
  fetchEgressEntries,
  createEgressEntry,
  deleteEgressEntry,
} from '../api/egress';
import type { EgressEntryCreate } from '../api/egress';
import LoadingSpinner from '../components/LoadingSpinner';

type FormValues = {
  endpoint_pattern: string;
  port: number;
  protocol: string;
  description: string;
};

export default function EgressAllowlist() {
  const qc = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const { data: entries = [], isLoading, error } = useQuery({
    queryKey: ['egress-allowlist'],
    queryFn: fetchEgressEntries,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteEgressEntry,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['egress-allowlist'] });
      setConfirmDelete(null);
    },
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    defaultValues: {
      endpoint_pattern: '',
      port: 443,
      protocol: 'https',
      description: '',
    },
  });

  const createMutation = useMutation({
    mutationFn: (payload: EgressEntryCreate) => createEgressEntry(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['egress-allowlist'] });
      reset();
    },
  });

  function onSubmit(values: FormValues) {
    createMutation.mutate({
      endpoint_pattern: values.endpoint_pattern,
      port: Number(values.port),
      protocol: values.protocol,
      description: values.description || undefined,
    });
  }

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
        Failed to load egress allowlist.
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-gray-900">Egress Allowlist</h1>
        <p className="mt-1 text-sm text-gray-500">
          Controls which external endpoints agents can call. Empty list = all
          endpoints allowed (default-open).
        </p>
      </div>

      {/* Table */}
      <div className="rounded-xl bg-white shadow-sm ring-1 ring-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-100">
            <thead>
              <tr className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                <th className="px-6 py-3">Pattern</th>
                <th className="px-6 py-3">Port</th>
                <th className="px-6 py-3">Protocol</th>
                <th className="px-6 py-3">Description</th>
                <th className="px-6 py-3">Created</th>
                <th className="px-6 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white text-sm text-gray-700">
              {entries.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-6 py-12 text-center text-gray-400"
                  >
                    No entries — all egress is currently allowed
                  </td>
                </tr>
              ) : (
                entries.map((entry) => (
                  <tr key={entry.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 font-mono text-xs text-gray-900">
                      {entry.endpoint_pattern}
                    </td>
                    <td className="px-6 py-4 font-mono text-xs text-gray-600">
                      {entry.port}
                    </td>
                    <td className="px-6 py-4">
                      <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold text-blue-700">
                        {entry.protocol}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-gray-500 max-w-xs">
                      <span className="truncate block">
                        {entry.description ?? '—'}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-gray-500 whitespace-nowrap">
                      {new Date(entry.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-6 py-4">
                      <button
                        onClick={() => setConfirmDelete(entry.id)}
                        className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600 transition-colors"
                        title="Delete"
                      >
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add entry form */}
      <div className="rounded-xl bg-white shadow-sm ring-1 ring-gray-200 p-6">
        <h2 className="mb-4 text-sm font-semibold text-gray-700">
          Add Allowlist Entry
        </h2>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {/* Endpoint Pattern */}
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Endpoint Pattern <span className="text-red-500">*</span>
              </label>
              <input
                {...register('endpoint_pattern', {
                  required: 'Endpoint pattern is required',
                })}
                placeholder="api.example.com or *.internal.com"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              {errors.endpoint_pattern && (
                <p className="mt-1 text-xs text-red-600">
                  {errors.endpoint_pattern.message}
                </p>
              )}
            </div>

            {/* Port */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Port <span className="text-red-500">*</span>
              </label>
              <input
                type="number"
                {...register('port', {
                  required: 'Port is required',
                  valueAsNumber: true,
                  min: { value: 1, message: 'Port must be at least 1' },
                  max: { value: 65535, message: 'Port must be at most 65535' },
                })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              {errors.port && (
                <p className="mt-1 text-xs text-red-600">
                  {errors.port.message}
                </p>
              )}
            </div>

            {/* Protocol */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Protocol
              </label>
              <select
                {...register('protocol')}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="https">https</option>
                <option value="http">http</option>
                <option value="grpc">grpc</option>
              </select>
            </div>

            {/* Description */}
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Description{' '}
                <span className="text-xs text-gray-400 font-normal">
                  (optional)
                </span>
              </label>
              <input
                {...register('description')}
                placeholder="e.g. Acme CRM integration"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>

          {createMutation.isError && (
            <div className="rounded-lg bg-red-50 px-4 py-2.5 text-sm text-red-600 ring-1 ring-red-200">
              Failed to add entry. Please try again.
            </div>
          )}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              <Plus size={16} />
              {createMutation.isPending ? 'Adding…' : 'Add Entry'}
            </button>
          </div>
        </form>
      </div>

      {/* Confirm delete dialog */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl space-y-4">
            <h2 className="text-base font-semibold text-gray-900">
              Delete Egress Entry?
            </h2>
            <p className="text-sm text-gray-500">
              This will immediately remove the rule. Agents may lose access to
              the affected endpoint.
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
