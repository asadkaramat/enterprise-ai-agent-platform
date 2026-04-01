import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Bot, MessagesSquare, Wrench, Settings } from 'lucide-react';

const nav = [
  { to: '/',         label: 'Dashboard', icon: LayoutDashboard },
  { to: '/agents',   label: 'Agents',    icon: Bot },
  { to: '/sessions', label: 'Sessions',  icon: MessagesSquare },
  { to: '/tools',    label: 'Tools',     icon: Wrench },
  { to: '/settings', label: 'Settings',  icon: Settings },
];

export default function Sidebar() {
  return (
    <aside className="flex h-screen w-60 flex-shrink-0 flex-col bg-gray-900 text-white">
      <div className="flex items-center gap-3 border-b border-gray-700 px-6 py-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600">
          <Bot size={18} />
        </div>
        <span className="text-sm font-semibold tracking-wide">Agent Platform</span>
      </div>
      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
        {nav.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-white'
              }`
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
