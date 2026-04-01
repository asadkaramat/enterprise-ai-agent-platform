import { useLocation } from 'react-router-dom';

const breadcrumbMap: Record<string, string> = {
  '/':           'Dashboard',
  '/agents':     'Agents',
  '/agents/new': 'Agents / New Agent',
  '/sessions':   'Sessions',
  '/tools':      'Tools',
  '/tools/new':  'Tools / Register Tool',
  '/settings':   'Settings',
};

function getLabel(pathname: string): string {
  if (breadcrumbMap[pathname]) return breadcrumbMap[pathname];
  if (pathname.match(/^\/agents\/[^/]+\/edit$/)) return 'Agents / Edit Agent';
  if (pathname.match(/^\/agents\/[^/]+$/))        return 'Agents / Detail';
  if (pathname.match(/^\/sessions\/[^/]+$/))       return 'Sessions / Detail';
  if (pathname.match(/^\/tools\/[^/]+\/edit$/))    return 'Tools / Edit Tool';
  return 'Agent Platform';
}

export default function Navbar() {
  const { pathname } = useLocation();
  const label = getLabel(pathname);
  const segments = label.split(' / ');

  return (
    <header className="flex h-14 items-center border-b border-gray-200 bg-white px-6">
      <p className="text-sm text-gray-500">
        {segments.map((seg, i) => (
          <span key={i}>
            {i > 0 && <span className="mx-1 text-gray-300">/</span>}
            <span className={i === segments.length - 1 ? 'font-semibold text-gray-800' : ''}>
              {seg}
            </span>
          </span>
        ))}
      </p>
    </header>
  );
}
