import { Link, useRouterState } from '@tanstack/react-router';
import { FiHome, FiFolder, FiBarChart2, FiUsers, FiSettings, FiX } from 'react-icons/fi';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { useUIStore } from '@/stores/ui.store';
import { useAuthStore } from '@/stores/auth.store';

type NavItem = { to: string; labelKey: string; icon: React.ReactNode; adminOnly?: boolean };

const NAV: NavItem[] = [
  { to: '/', labelKey: 'nav.dashboard', icon: <FiHome /> },
  { to: '/projects', labelKey: 'nav.projects', icon: <FiFolder /> },
  { to: '/analytics', labelKey: 'nav.analytics', icon: <FiBarChart2 /> },
  { to: '/admin', labelKey: 'nav.admin', icon: <FiUsers />, adminOnly: true },
  { to: '/settings', labelKey: 'nav.settings', icon: <FiSettings /> }
];

export function Sidenav() {
  const { t } = useTranslation();
  const drawerOpen = useUIStore((s) => s.drawerOpen);
  const setDrawer = useUIStore((s) => s.setDrawer);
  const role = useAuthStore((s) => s.user?.role);
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  const items = NAV.filter((n) => !n.adminOnly || role === 'admin');

  return (
    <>
      <div
        onClick={() => setDrawer(false)}
        className={clsx(
          'fixed inset-0 z-30 bg-slate-900/40 backdrop-blur-sm transition-opacity lg:hidden',
          drawerOpen ? 'opacity-100' : 'pointer-events-none opacity-0'
        )}
      />

      <aside
        className={clsx(
          'fixed z-40 top-0 start-0 h-full w-72 bg-white border-e border-slate-200 shadow-soft transition-transform',
          'lg:translate-x-0 lg:static lg:shadow-none',
          drawerOpen ? 'translate-x-0' : 'rtl:translate-x-full ltr:-translate-x-full'
        )}
      >
        <div className="flex items-center justify-between px-5 h-16 border-b border-slate-100">
          <Link to="/" className="flex items-center gap-2 font-semibold text-slate-900">
            <span className="w-8 h-8 rounded-lg bg-brand-600 text-white grid place-items-center">PM</span>
            <span>PFE Marketing</span>
          </Link>
          <button
            className="lg:hidden text-slate-500 hover:text-slate-800"
            onClick={() => setDrawer(false)}
            aria-label={t('common.close')}
          >
            <FiX size={22} />
          </button>
        </div>

        <nav className="p-3 space-y-1">
          {items.map((n) => {
            const active = pathname === n.to || (n.to !== '/' && pathname.startsWith(n.to));
            return (
              <Link
                key={n.to}
                to={n.to}
                onClick={() => setDrawer(false)}
                className={clsx(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition',
                  active
                    ? 'bg-brand-50 text-brand-700'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                )}
              >
                <span className="text-lg">{n.icon}</span>
                <span>{t(n.labelKey)}</span>
                {n.adminOnly && <span className="ms-auto badge-admin">admin</span>}
              </Link>
            );
          })}
        </nav>

        <div className="absolute bottom-0 inset-x-0 p-4 border-t border-slate-100 bg-slate-50/50 text-xs text-slate-500">
          v0.1.0 · {t('common.online')}
        </div>
      </aside>
    </>
  );
}
