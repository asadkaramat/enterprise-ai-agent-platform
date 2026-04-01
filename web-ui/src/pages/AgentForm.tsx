import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchAgent, createAgent, updateAgent } from '../api/agents';
import LoadingSpinner from '../components/LoadingSpinner';
import type { AgentCreate } from '../types';

const MODELS = ['llama3.2', 'llama3.1', 'mistral', 'qwen2.5'];

export default function AgentForm() {
  const { id } = useParams<{ id: string }>();
  const isEdit = !!id;
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => fetchAgent(id!),
    enabled: isEdit,
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<AgentCreate>({
    defaultValues: {
      name: '',
      description: '',
      system_prompt: '',
      model: 'llama3.2',
      max_steps: 10,
      token_budget: 8000,
      session_timeout: 300,
      memory_enabled: false,
    },
  });

  useEffect(() => {
    if (agent) reset(agent);
  }, [agent, reset]);

  const mutation = useMutation({
    mutationFn: (data: AgentCreate) =>
      isEdit ? updateAgent(id!, data) : createAgent(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] });
      if (isEdit) qc.invalidateQueries({ queryKey: ['agent', id] });
      navigate('/agents');
    },
  });

  if (isEdit && isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6 text-xl font-bold text-gray-900">
        {isEdit ? 'Edit Agent' : 'Create Agent'}
      </h1>

      <form
        onSubmit={handleSubmit((d) => mutation.mutate(d))}
        className="space-y-5 rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200"
      >
        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Name <span className="text-red-500">*</span>
          </label>
          <input
            {...register('name', { required: 'Name is required' })}
            placeholder="My Agent"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          {errors.name && (
            <p className="mt-1 text-xs text-red-600">{errors.name.message}</p>
          )}
        </div>

        {/* Description */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Description
          </label>
          <input
            {...register('description')}
            placeholder="Optional description of this agent's purpose"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* System Prompt */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            System Prompt <span className="text-red-500">*</span>
          </label>
          <textarea
            rows={7}
            {...register('system_prompt', { required: 'System prompt is required' })}
            placeholder="You are a helpful assistant that..."
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-y font-mono"
          />
          {errors.system_prompt && (
            <p className="mt-1 text-xs text-red-600">{errors.system_prompt.message}</p>
          )}
        </div>

        {/* Model */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Model</label>
          <select
            {...register('model')}
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {MODELS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>

        {/* Numeric fields */}
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Max Steps
            </label>
            <input
              type="number"
              min={1}
              max={100}
              {...register('max_steps', { valueAsNumber: true, min: 1 })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Token Budget
            </label>
            <input
              type="number"
              min={100}
              {...register('token_budget', { valueAsNumber: true, min: 100 })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Timeout (s)
            </label>
            <input
              type="number"
              min={30}
              {...register('session_timeout', { valueAsNumber: true, min: 30 })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
        </div>

        {/* Memory toggle */}
        <div className="flex items-center gap-3 rounded-lg bg-gray-50 px-4 py-3">
          <input
            type="checkbox"
            id="memory_enabled"
            {...register('memory_enabled')}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <div>
            <label
              htmlFor="memory_enabled"
              className="text-sm font-medium text-gray-700 cursor-pointer"
            >
              Enable Memory
            </label>
            <p className="text-xs text-gray-500">
              Agent will retain context across sessions
            </p>
          </div>
        </div>

        {mutation.isError && (
          <div className="rounded-lg bg-red-50 px-4 py-2.5 text-sm text-red-600 ring-1 ring-red-200">
            Failed to save agent. Please try again.
          </div>
        )}

        <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
          <button
            type="button"
            onClick={() => navigate('/agents')}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={mutation.isPending}
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {mutation.isPending
              ? 'Saving…'
              : isEdit
              ? 'Update Agent'
              : 'Create Agent'}
          </button>
        </div>
      </form>
    </div>
  );
}
