import type { ReactNode } from 'react';

interface Props {
  title: string;
  value: string | number;
  icon: ReactNode;
  trend?: string;
  trendUp?: boolean;
}

export default function MetricCard({ title, value, icon, trend, trendUp }: Props) {
  return (
    <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-gray-500">{title}</p>
        <span className="rounded-lg bg-blue-50 p-2 text-blue-600">{icon}</span>
      </div>
      <p className="mt-3 text-3xl font-bold text-gray-900">{value}</p>
      {trend && (
        <p className={`mt-1 text-xs ${trendUp ? 'text-green-600' : 'text-gray-400'}`}>
          {trend}
        </p>
      )}
    </div>
  );
}
