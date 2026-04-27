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

  const isActive = (to: string) => pathname === to || (to !== '/' && pathname.startsWith(to));

  return (
    <>
      {/* Permanent icon rail — visible on lg+ only. */}
      <aside
        className="hidden lg:flex flex-col w-16 shrink-0 bg-white border-e border-slate-200 sticky top-0 h-screen z-10"
        aria-label={t('nav.railLabel', { defaultValue: 'Primary navigation' })}
      >
        <Link
          to="/"
          className="h-16 flex items-center justify-center border-b border-slate-100"
          title={t('common.menu')}
        >
          <span className="w-8 h-8 rounded-lg bg-brand-600 text-white grid place-items-center text-xs font-semibold">
            PM
          </span>
        </Link>

        <nav className="flex-1 p-2 space-y-1" aria-label={t('common.menu')}>
          {items.map((n) => {
            const active = isActive(n.to);
            return (
              <Link
                key={n.to}
                to={n.to}
                title={t(n.labelKey)}
                aria-label={t(n.labelKey)}
                className={clsx(
                  'group relative flex items-center justify-center h-11 w-11 mx-auto rounded-lg text-lg transition',
                  active
                    ? 'bg-brand-50 text-brand-700'
                    : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900'
                )}
                aria-current={active ? 'page' : undefined}
              >
                {active && (
                  <span className="absolute start-0 top-1/2 -translate-y-1/2 h-6 w-1 rounded-e-full bg-brand-600" />
                )}
                {n.icon}
                {n.adminOnly && (
                  <span className="absolute -top-0.5 -end-0.5 h-2 w-2 rounded-full bg-amber-400 ring-2 ring-white" />
                )}
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* Full drawer overlay — toggleable on all breakpoints. */}
      <div
        onClick={() => setDrawer(false)}
        className={clsx(
          'fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-sm transition-opacity',
          drawerOpen ? 'opacity-100' : 'pointer-events-none opacity-0'
        )}
      />

      <aside
        className={clsx(
          'fixed z-50 top-0 start-0 h-full w-72 bg-white border-e border-slate-200 shadow-soft transition-transform',
          drawerOpen ? 'translate-x-0' : 'rtl:translate-x-full ltr:-translate-x-full'
        )}
        aria-hidden={!drawerOpen}
      >
        <div className="flex items-center justify-between px-5 h-16 border-b border-slate-100">
          <Link
            to="/"
            onClick={() => setDrawer(false)}
            className="flex items-center gap-2 font-semibold text-slate-900"
          >
            <span className="w-8 h-8 rounded-lg bg-brand-600 text-white grid place-items-center">PM</span>
            <span>PFE Marketing</span>
          </Link>
          <button
            className="text-slate-500 hover:text-slate-800"
            onClick={() => setDrawer(false)}
            aria-label={t('common.close')}
          >
            <FiX size={22} />
          </button>
        </div>

        <nav className="p-3 space-y-1" aria-label={t('common.menu')}>
          {items.map((n) => {
            const active = isActive(n.to);
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
                aria-current={active ? 'page' : undefined}
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
