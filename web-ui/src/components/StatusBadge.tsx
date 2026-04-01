import type { SessionStatus } from '../types';

const config: Record<SessionStatus, { label: string; classes: string }> = {
  active:     { label: 'Active',      classes: 'bg-green-100 text-green-800' },
  completed:  { label: 'Completed',   classes: 'bg-blue-100 text-blue-800' },
  error:      { label: 'Error',       classes: 'bg-red-100 text-red-800' },
  terminated: { label: 'Terminated',  classes: 'bg-gray-100 text-gray-600' },
};

export default function StatusBadge({ status }: { status: SessionStatus }) {
  const { label, classes } = config[status] ?? config.terminated;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${classes}`}
    >
      {label}
    </span>
  );
}
