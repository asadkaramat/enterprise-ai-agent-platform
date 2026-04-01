import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchTool, createTool, updateTool } from '../api/tools';
import LoadingSpinner from '../components/LoadingSpinner';
import type { ToolCreate } from '../types';

type FormValues = {
  name: string;
  description: string;
  version: string;
  endpoint_url: string;
  http_method: 'POST' | 'GET' | 'PUT';
  auth_type: 'none' | 'api_key';
  input_schema_raw: string;
  output_schema_raw: string;
  auth_config_raw: string;
  is_cacheable: boolean;
  cache_ttl_seconds: number;
};

function tryParseJson(
  raw: string
): { value: Record<string, unknown> | undefined; error: string | null } {
  if (!raw.trim()) return { value: undefined, error: null };
  try {
    return { value: JSON.parse(raw), error: null };
  } catch (e) {
    return { value: undefined, error: (e as Error).message };
  }
}

export default function ToolForm() {
  const { id } = useParams<{ id: string }>();
  const isEdit = !!id;
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [inputSchemaErr, setInputSchemaErr] = useState<string | null>(null);
  const [outputSchemaErr, setOutputSchemaErr] = useState<string | null>(null);
  const [authConfigErr, setAuthConfigErr] = useState<string | null>(null);

  const { data: tool, isLoading } = useQuery({
    queryKey: ['tool', id],
    queryFn: () => fetchTool(id!),
    enabled: isEdit,
  });

  const {
    register,
    handleSubmit,
    watch,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    defaultValues: {
      name: '',
      description: '',
      version: '1.0.0',
      endpoint_url: '',
      http_method: 'POST',
      auth_type: 'none',
      input_schema_raw: '',
      output_schema_raw: '',
      auth_config_raw: '',
      is_cacheable: false,
      cache_ttl_seconds: 300,
    },
  });

  const authType = watch('auth_type');
  const isCacheable = watch('is_cacheable');

  useEffect(() => {
    if (tool) {
      reset({
        name: tool.name,
        description: tool.description,
        version: tool.version,
        endpoint_url: tool.endpoint_url,
        http_method: tool.http_method,
        auth_type: tool.auth_type,
        input_schema_raw: tool.input_schema
          ? JSON.stringify(tool.input_schema, null, 2)
          : '',
        output_schema_raw: tool.output_schema
          ? JSON.stringify(tool.output_schema, null, 2)
          : '',
        auth_config_raw: tool.auth_config
          ? JSON.stringify(tool.auth_config, null, 2)
          : '',
        is_cacheable: tool.is_cacheable ?? false,
        cache_ttl_seconds: tool.cache_ttl_seconds ?? 300,
      });
    }
  }, [tool, reset]);

  const mutation = useMutation({
    mutationFn: (data: ToolCreate) =>
      isEdit ? updateTool(id!, data) : createTool(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tools'] });
      navigate('/tools');
    },
  });

  function onSubmit(values: FormValues) {
    const inputResult = tryParseJson(values.input_schema_raw);
    const outputResult = tryParseJson(values.output_schema_raw);
    const authResult = tryParseJson(values.auth_config_raw);

    setInputSchemaErr(inputResult.error);
    setOutputSchemaErr(outputResult.error);
    setAuthConfigErr(authResult.error);

    const hasAuthErr = values.auth_type !== 'none' && authResult.error;
    if (inputResult.error || outputResult.error || hasAuthErr) return;

    const payload: ToolCreate = {
      name: values.name,
      description: values.description,
      version: values.version,
      endpoint_url: values.endpoint_url,
      http_method: values.http_method,
      auth_type: values.auth_type,
      input_schema: inputResult.value,
      output_schema: outputResult.value,
      auth_config:
        values.auth_type !== 'none' ? authResult.value : undefined,
      is_cacheable: values.is_cacheable,
      cache_ttl_seconds: values.is_cacheable ? values.cache_ttl_seconds : undefined,
    };

    mutation.mutate(payload);
  }

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
        {isEdit ? 'Edit Tool' : 'Register Tool'}
      </h1>

      <form
        onSubmit={handleSubmit(onSubmit)}
        className="space-y-5 rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200"
      >
        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Name <span className="text-red-500">*</span>
          </label>
          <input
            {...register('name', { required: 'Name is required' })}
            placeholder="my-tool"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          {errors.name && (
            <p className="mt-1 text-xs text-red-600">{errors.name.message}</p>
          )}
        </div>

        {/* Description */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Description <span className="text-red-500">*</span>
          </label>
          <input
            {...register('description', { required: 'Description is required' })}
            placeholder="What this tool does"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          {errors.description && (
            <p className="mt-1 text-xs text-red-600">
              {errors.description.message}
            </p>
          )}
        </div>

        {/* Version + Method row */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Version
            </label>
            <input
              {...register('version')}
              placeholder="1.0.0"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              HTTP Method
            </label>
            <select
              {...register('http_method')}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="POST">POST</option>
              <option value="GET">GET</option>
              <option value="PUT">PUT</option>
            </select>
          </div>
        </div>

        {/* Endpoint URL */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Endpoint URL <span className="text-red-500">*</span>
          </label>
          <input
            {...register('endpoint_url', {
              required: 'Endpoint URL is required',
            })}
            placeholder="https://api.example.com/v1/tool"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          {errors.endpoint_url && (
            <p className="mt-1 text-xs text-red-600">
              {errors.endpoint_url.message}
            </p>
          )}
        </div>

        {/* Input Schema */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Input Schema{' '}
            <span className="text-xs text-gray-400 font-normal">(JSON)</span>
          </label>
          <textarea
            rows={4}
            {...register('input_schema_raw', {
              onChange: () => setInputSchemaErr(null),
            })}
            placeholder={'{\n  "type": "object",\n  "properties": {}\n}'}
            className={`w-full rounded-lg border px-3 py-2 text-sm font-mono shadow-sm focus:outline-none focus:ring-1 resize-y ${
              inputSchemaErr
                ? 'border-red-400 focus:border-red-500 focus:ring-red-400'
                : 'border-gray-300 focus:border-blue-500 focus:ring-blue-500'
            }`}
          />
          {inputSchemaErr && (
            <p className="mt-1 text-xs text-red-600">
              Invalid JSON: {inputSchemaErr}
            </p>
          )}
        </div>

        {/* Output Schema */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Output Schema{' '}
            <span className="text-xs text-gray-400 font-normal">(JSON)</span>
          </label>
          <textarea
            rows={4}
            {...register('output_schema_raw', {
              onChange: () => setOutputSchemaErr(null),
            })}
            placeholder={'{\n  "type": "object",\n  "properties": {}\n}'}
            className={`w-full rounded-lg border px-3 py-2 text-sm font-mono shadow-sm focus:outline-none focus:ring-1 resize-y ${
              outputSchemaErr
                ? 'border-red-400 focus:border-red-500 focus:ring-red-400'
                : 'border-gray-300 focus:border-blue-500 focus:ring-blue-500'
            }`}
          />
          {outputSchemaErr && (
            <p className="mt-1 text-xs text-red-600">
              Invalid JSON: {outputSchemaErr}
            </p>
          )}
        </div>

        {/* Auth Type */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Auth Type
          </label>
          <select
            {...register('auth_type')}
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="none">None</option>
            <option value="api_key">API Key</option>
          </select>
        </div>

        {/* Auth Config (shown only when auth_type != none) */}
        {authType !== 'none' && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Auth Config{' '}
              <span className="text-xs text-gray-400 font-normal">(JSON)</span>
            </label>
            <textarea
              rows={3}
              {...register('auth_config_raw', {
                onChange: () => setAuthConfigErr(null),
              })}
              placeholder={'{\n  "header": "X-API-Key",\n  "value": "secret"\n}'}
              className={`w-full rounded-lg border px-3 py-2 text-sm font-mono shadow-sm focus:outline-none focus:ring-1 resize-y ${
                authConfigErr
                  ? 'border-red-400 focus:border-red-500 focus:ring-red-400'
                  : 'border-gray-300 focus:border-blue-500 focus:ring-blue-500'
              }`}
            />
            {authConfigErr && (
              <p className="mt-1 text-xs text-red-600">
                Invalid JSON: {authConfigErr}
              </p>
            )}
          </div>
        )}

        {/* Cache results */}
        <div className="flex items-start gap-3">
          <input
            type="checkbox"
            id="is_cacheable"
            {...register('is_cacheable')}
            className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <div>
            <label
              htmlFor="is_cacheable"
              className="block text-sm font-medium text-gray-700"
            >
              Cache results (idempotent tool)
            </label>
            <p className="mt-0.5 text-xs text-gray-500">
              When enabled, identical calls return the cached result for the configured TTL.
            </p>
          </div>
        </div>

        {/* Cache TTL — shown only when is_cacheable is true */}
        {isCacheable && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Cache TTL (seconds)
            </label>
            <input
              type="number"
              min={30}
              {...register('cache_ttl_seconds', {
                valueAsNumber: true,
                min: { value: 30, message: 'Minimum TTL is 30 seconds' },
              })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            {errors.cache_ttl_seconds && (
              <p className="mt-1 text-xs text-red-600">
                {errors.cache_ttl_seconds.message}
              </p>
            )}
          </div>
        )}

        {mutation.isError && (
          <div className="rounded-lg bg-red-50 px-4 py-2.5 text-sm text-red-600 ring-1 ring-red-200">
            Failed to save tool. Please try again.
          </div>
        )}

        <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
          <button
            type="button"
            onClick={() => navigate('/tools')}
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
              ? 'Update Tool'
              : 'Register Tool'}
          </button>
        </div>
      </form>
    </div>
  );
}
