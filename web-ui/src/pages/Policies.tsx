import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { Trash2, ChevronDown, ChevronRight } from 'lucide-react';
import {
  fetchPolicies,
  createPolicy,
  updatePolicy,
  deletePolicy,
} from '../api/policies';
import LoadingSpinner from '../components/LoadingSpinner';
import type { Policy } from '../types';

// ── DLP form ──────────────────────────────────────────────────────────────────

type DlpFormValues = {
  name: string;
  keyword_blocklist: string;
  redact_patterns_raw: string;
  max_output_chars: string;
};

interface DlpPolicyBody {
  type: string;
  keyword_blocklist: string[];
  redact_patterns: Array<{ pattern: string; name: string }>;
  max_output_chars?: number;
}

function parseDlpBody(policy: Policy): DlpPolicyBody | null {
  try {
    const parsed = JSON.parse(policy.policy_body);
    if (parsed?.type === 'output_dlp') return parsed as DlpPolicyBody;
    return null;
  } catch {
    return null;
  }
}

// ── Toggle switch (reuses AgentDetail pattern) ────────────────────────────────

function ToggleSwitch({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onChange}
      disabled={disabled}
      className={`relative inline-flex h-5 w-9 rounded-full transition-colors focus:outline-none disabled:opacity-50 ${
        checked ? 'bg-blue-600' : 'bg-gray-300'
      }`}
      role="switch"
      aria-checked={checked}
    >
      <span
        className={`inline-block h-4 w-4 translate-y-0.5 rounded-full bg-white shadow transition-transform ${
          checked ? 'translate-x-4' : 'translate-x-0.5'
        }`}
      />
    </button>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Policies() {
  const qc = useQueryClient();
  const [allPoliciesOpen, setAllPoliciesOpen] = useState(true);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [redactParseErr, setRedactParseErr] = useState<string | null>(null);

  const { data: policies = [], isLoading, error } = useQuery({
    queryKey: ['policies'],
    queryFn: fetchPolicies,
  });

  const createMutation = useMutation({
    mutationFn: createPolicy,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['policies'] });
      reset();
      setRedactParseErr(null);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      updatePolicy(id, { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['policies'] }),
  });

  const deleteMutation = useMutation({
    mutationFn: deletePolicy,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['policies'] });
      setConfirmDelete(null);
    },
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<DlpFormValues>({
    defaultValues: {
      name: '',
      keyword_blocklist: '',
      redact_patterns_raw: '',
      max_output_chars: '',
    },
  });

  function onDlpSubmit(values: DlpFormValues) {
    // Parse redact_patterns if provided
    let redactPatterns: Array<{ pattern: string; name: string }> = [];
    if (values.redact_patterns_raw.trim()) {
      try {
        redactPatterns = JSON.parse(values.redact_patterns_raw);
        setRedactParseErr(null);
      } catch (e) {
        setRedactParseErr((e as Error).message);
        return;
      }
    } else {
      setRedactParseErr(null);
    }

    const keywords = values.keyword_blocklist
      .split(',')
      .map((k) => k.trim())
      .filter(Boolean);

    const maxChars = values.max_output_chars
      ? Number(values.max_output_chars)
      : undefined;

    const policyBody: DlpPolicyBody = {
      type: 'output_dlp',
      keyword_blocklist: keywords,
      redact_patterns: redactPatterns,
      ...(maxChars !== undefined ? { max_output_chars: maxChars } : {}),
    };

    createMutation.mutate({
      name: values.name,
      scope: 'tenant',
      policy_lang: 'inline',
      policy_body: JSON.stringify(policyBody),
    });
  }

  const dlpPolicies = policies.filter((p) => parseDlpBody(p) !== null);

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
        Failed to load policies.
      </div>
    );
  }

  return (
    <div className="space-y-8 max-w-4xl">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Policies</h1>
        <p className="mt-1 text-sm text-gray-500">
          Manage tenant-level policies including output DLP rules.
        </p>
      </div>

      {/* ── Section A: DLP Rules ──────────────────────────────────────────── */}
      <div className="space-y-4">
        <div className="rounded-xl bg-white shadow-sm ring-1 ring-gray-200 overflow-hidden">
          <div className="border-b border-gray-200 px-6 py-4">
            <h2 className="text-sm font-semibold text-gray-700">
              Output DLP Rules
            </h2>
            <p className="mt-0.5 text-xs text-gray-500">
              These rules are applied to every agent response before delivery.
            </p>
          </div>

          {/* Existing DLP policies */}
          {dlpPolicies.length === 0 ? (
            <div className="px-6 py-8 text-center text-sm text-gray-400">
              No DLP rules configured yet.
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {dlpPolicies.map((policy) => {
                const body = parseDlpBody(policy)!;
                return (
                  <div
                    key={policy.id}
                    className="flex flex-wrap items-start justify-between gap-4 px-6 py-4"
                  >
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="text-sm font-medium text-gray-900">
                        {policy.name}
                      </p>
                      {body.keyword_blocklist.length > 0 && (
                        <p className="text-xs text-gray-500">
                          <span className="font-medium text-gray-600">
                            Blocked keywords:{' '}
                          </span>
                          {body.keyword_blocklist.join(', ')}
                        </p>
                      )}
                      {body.max_output_chars !== undefined && (
                        <p className="text-xs text-gray-500">
                          <span className="font-medium text-gray-600">
                            Max output:{' '}
                          </span>
                          {body.max_output_chars.toLocaleString()} chars
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <ToggleSwitch
                        checked={policy.enabled}
                        onChange={() =>
                          toggleMutation.mutate({
                            id: policy.id,
                            enabled: !policy.enabled,
                          })
                        }
                        disabled={toggleMutation.isPending}
                      />
                      <button
                        onClick={() => setConfirmDelete(policy.id)}
                        className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600 transition-colors"
                        title="Delete"
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Add DLP Rule form */}
          <div className="border-t border-gray-200 bg-gray-50 px-6 py-5">
            <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Add DLP Rule
            </h3>
            <form onSubmit={handleSubmit(onDlpSubmit)} className="space-y-4">
              {/* Name */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  {...register('name', { required: 'Name is required' })}
                  placeholder="e.g. Block PII Keywords"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                {errors.name && (
                  <p className="mt-1 text-xs text-red-600">
                    {errors.name.message}
                  </p>
                )}
              </div>

              {/* Keyword Blocklist */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Keyword Blocklist{' '}
                  <span className="text-xs text-gray-400 font-normal">
                    (optional)
                  </span>
                </label>
                <input
                  {...register('keyword_blocklist')}
                  placeholder="ssn, password, secret"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <p className="mt-0.5 text-xs text-gray-500">
                  Responses containing these words will be blocked
                </p>
              </div>

              {/* Redact Patterns */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Redact Patterns{' '}
                  <span className="text-xs text-gray-400 font-normal">
                    (optional, advanced — JSON array)
                  </span>
                </label>
                <textarea
                  rows={3}
                  {...register('redact_patterns_raw', {
                    onChange: () => setRedactParseErr(null),
                  })}
                  placeholder={'[{"pattern": "\\\\d{3}-\\\\d{2}-\\\\d{4}", "name": "SSN"}]'}
                  className={`w-full rounded-lg border px-3 py-2 text-sm font-mono shadow-sm focus:outline-none focus:ring-1 resize-y ${
                    redactParseErr
                      ? 'border-red-400 focus:border-red-500 focus:ring-red-400'
                      : 'border-gray-300 focus:border-blue-500 focus:ring-blue-500'
                  }`}
                />
                {redactParseErr && (
                  <p className="mt-1 text-xs text-red-600">
                    Invalid JSON: {redactParseErr}
                  </p>
                )}
              </div>

              {/* Max Output Chars */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Max Output Chars{' '}
                  <span className="text-xs text-gray-400 font-normal">
                    (optional)
                  </span>
                </label>
                <input
                  type="number"
                  {...register('max_output_chars', {
                    min: { value: 100, message: 'Minimum value is 100' },
                  })}
                  placeholder="e.g. 4000"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <p className="mt-0.5 text-xs text-gray-500">
                  Maximum response length (blank = unlimited)
                </p>
                {errors.max_output_chars && (
                  <p className="mt-1 text-xs text-red-600">
                    {errors.max_output_chars.message}
                  </p>
                )}
              </div>

              {createMutation.isError && (
                <div className="rounded-lg bg-red-50 px-4 py-2.5 text-sm text-red-600 ring-1 ring-red-200">
                  Failed to create policy. Please try again.
                </div>
              )}

              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={createMutation.isPending}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                >
                  {createMutation.isPending ? 'Saving…' : 'Add DLP Rule'}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>

      {/* ── Section B: All Policies (raw view) ───────────────────────────── */}
      <div className="rounded-xl bg-white shadow-sm ring-1 ring-gray-200 overflow-hidden">
        {/* Collapsible header */}
        <button
          type="button"
          onClick={() => setAllPoliciesOpen((v) => !v)}
          className="flex w-full items-center justify-between px-6 py-4 text-left hover:bg-gray-50 transition-colors"
        >
          <div>
            <h2 className="text-sm font-semibold text-gray-700">
              All Policies
            </h2>
            <p className="mt-0.5 text-xs text-gray-500">
              Raw view of every policy for this tenant.
            </p>
          </div>
          {allPoliciesOpen ? (
            <ChevronDown size={18} className="text-gray-400 shrink-0" />
          ) : (
            <ChevronRight size={18} className="text-gray-400 shrink-0" />
          )}
        </button>

        {allPoliciesOpen && (
          <>
            <div className="border-t border-gray-100 overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-100">
                <thead>
                  <tr className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    <th className="px-6 py-3">Name</th>
                    <th className="px-6 py-3">Scope</th>
                    <th className="px-6 py-3">Language</th>
                    <th className="px-6 py-3">Version</th>
                    <th className="px-6 py-3">Enabled</th>
                    <th className="px-6 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white text-sm text-gray-700">
                  {policies.length === 0 ? (
                    <tr>
                      <td
                        colSpan={6}
                        className="px-6 py-10 text-center text-gray-400"
                      >
                        No policies found.
                      </td>
                    </tr>
                  ) : (
                    policies.map((policy) => (
                      <>
                        <tr
                          key={policy.id}
                          className="hover:bg-gray-50 cursor-pointer"
                          onClick={() =>
                            setExpandedRow(
                              expandedRow === policy.id ? null : policy.id
                            )
                          }
                        >
                          <td className="px-6 py-4 font-medium text-gray-900">
                            <div className="flex items-center gap-2">
                              {expandedRow === policy.id ? (
                                <ChevronDown
                                  size={14}
                                  className="text-gray-400 shrink-0"
                                />
                              ) : (
                                <ChevronRight
                                  size={14}
                                  className="text-gray-400 shrink-0"
                                />
                              )}
                              {policy.name}
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-semibold text-purple-700">
                              {policy.scope}
                            </span>
                          </td>
                          <td className="px-6 py-4 font-mono text-xs text-gray-600">
                            {policy.policy_lang}
                          </td>
                          <td className="px-6 py-4 font-mono text-xs text-gray-600">
                            v{policy.version}
                          </td>
                          <td
                            className="px-6 py-4"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <ToggleSwitch
                              checked={policy.enabled}
                              onChange={() =>
                                toggleMutation.mutate({
                                  id: policy.id,
                                  enabled: !policy.enabled,
                                })
                              }
                              disabled={toggleMutation.isPending}
                            />
                          </td>
                          <td
                            className="px-6 py-4"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <button
                              onClick={() => setConfirmDelete(policy.id)}
                              className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600 transition-colors"
                              title="Delete"
                            >
                              <Trash2 size={15} />
                            </button>
                          </td>
                        </tr>
                        {expandedRow === policy.id && (
                          <tr key={`${policy.id}-body`}>
                            <td
                              colSpan={6}
                              className="bg-gray-50 px-6 py-4"
                            >
                              <pre className="overflow-auto rounded-lg bg-white p-4 text-xs text-gray-700 font-mono whitespace-pre-wrap max-h-64 ring-1 ring-gray-200">
                                {(() => {
                                  try {
                                    return JSON.stringify(
                                      JSON.parse(policy.policy_body),
                                      null,
                                      2
                                    );
                                  } catch {
                                    return policy.policy_body;
                                  }
                                })()}
                              </pre>
                            </td>
                          </tr>
                        )}
                      </>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {/* Confirm delete dialog */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl space-y-4">
            <h2 className="text-base font-semibold text-gray-900">
              Delete Policy?
            </h2>
            <p className="text-sm text-gray-500">
              This will disable and remove the policy. This action cannot be
              undone.
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
