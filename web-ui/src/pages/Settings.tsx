import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useMutation } from '@tanstack/react-query';
import { CheckCircle, XCircle, KeyRound, Wifi } from 'lucide-react';
import { useApiKey } from '../hooks/useApiKey';
import { checkHealth } from '../api/audit';

interface FormValues {
  apiKey: string;
}

export default function Settings() {
  const { apiKey, setApiKey, hasApiKey } = useApiKey();
  const [testResult, setTestResult] = useState<'ok' | 'fail' | null>(null);
  const [saved, setSaved] = useState(false);

  const { register, handleSubmit } = useForm<FormValues>({
    defaultValues: { apiKey },
  });

  const testMutation = useMutation({
    mutationFn: checkHealth,
    onSuccess: () => setTestResult('ok'),
    onError: () => setTestResult('fail'),
  });

  function onSave({ apiKey: key }: FormValues) {
    setApiKey(key.trim());
    setTestResult(null);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Settings</h1>
        <p className="mt-1 text-sm text-gray-500">
          Configure your API key to connect to the platform.
        </p>
      </div>

      <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200 space-y-5">
        {/* Status indicator */}
        <div className="flex items-center gap-2">
          {hasApiKey ? (
            <>
              <CheckCircle size={18} className="text-green-500" />
              <span className="text-sm font-medium text-green-700">Connected</span>
            </>
          ) : (
            <>
              <XCircle size={18} className="text-gray-400" />
              <span className="text-sm font-medium text-gray-500">Not configured</span>
            </>
          )}
        </div>

        <form onSubmit={handleSubmit(onSave)} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              API Key
            </label>
            <div className="relative">
              <KeyRound
                size={16}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
              />
              <input
                type="password"
                autoComplete="off"
                placeholder="sk-…"
                {...register('apiKey')}
                className="w-full rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>

          <div className="flex gap-3">
            <button
              type="submit"
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
            >
              {saved ? 'Saved!' : 'Save API Key'}
            </button>
            <button
              type="button"
              onClick={() => testMutation.mutate()}
              disabled={!hasApiKey || testMutation.isPending}
              className="flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
            >
              <Wifi size={15} />
              {testMutation.isPending ? 'Testing…' : 'Test Connection'}
            </button>
          </div>
        </form>

        {testResult === 'ok' && (
          <div className="flex items-center gap-1.5 rounded-lg bg-green-50 px-3 py-2 text-sm text-green-700">
            <CheckCircle size={15} />
            Connection successful — gateway is reachable.
          </div>
        )}
        {testResult === 'fail' && (
          <div className="flex items-center gap-1.5 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
            <XCircle size={15} />
            Connection failed — check your API key and that the gateway is running at{' '}
            <span className="font-mono">localhost:8000</span>.
          </div>
        )}
      </div>

      <div className="rounded-xl bg-gray-50 p-4 ring-1 ring-gray-200 text-xs text-gray-500 space-y-1">
        <p className="font-medium text-gray-700">About this app</p>
        <p>API Gateway: <span className="font-mono">http://localhost:8000</span></p>
        <p>Auth method: <span className="font-mono">X-API-Key</span> header</p>
        <p>Key stored in: <span className="font-mono">localStorage[&quot;agent_platform_api_key&quot;]</span></p>
      </div>
    </div>
  );
}
