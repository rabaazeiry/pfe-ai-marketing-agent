import { FiMenu, FiLogOut, FiBell } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import { useUIStore } from '@/stores/ui.store';
import { useAuthStore } from '@/stores/auth.store';
import { useNavigate } from '@tanstack/react-router';
import { closeSocket } from '@/lib/ws/socket';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';

export function Topbar() {
  const { t } = useTranslation();
  const toggleDrawer = useUIStore((s) => s.toggleDrawer);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();

  const handleLogout = () => {
    closeSocket();
    logout();
    navigate({ to: '/login' });
  };

  return (
    <header className="sticky top-0 z-20 h-16 bg-white/80 backdrop-blur border-b border-slate-200 flex items-center px-4 gap-3">
      <button
        className="lg:hidden p-2 rounded-lg hover:bg-slate-100 text-slate-600"
        onClick={toggleDrawer}
        aria-label={t('common.menu')}
      >
        <FiMenu size={22} />
      </button>

      <div className="flex-1" />

      <LanguageSwitcher />

      <button
        className="p-2 rounded-lg hover:bg-slate-100 text-slate-500 relative"
        aria-label={t('common.notifications')}
      >
        <FiBell size={20} />
        <span className="absolute top-1.5 end-1.5 w-2 h-2 rounded-full bg-red-500" />
      </button>

      {user && (
        <div className="flex items-center gap-3 ps-3 border-s border-slate-200">
          <div className="text-end hidden sm:block">
            <div className="text-sm font-medium text-slate-800">
              {user.firstName} {user.lastName}
            </div>
            <div className="text-xs text-slate-500">
              {user.email} · <span className={user.role === 'admin' ? 'badge-admin' : 'badge-user'}>{user.role}</span>
            </div>
          </div>
          <div className="w-9 h-9 rounded-full bg-brand-100 text-brand-700 grid place-items-center text-sm font-semibold">
            {user.firstName.charAt(0)}
            {user.lastName.charAt(0)}
          </div>
          <button
            onClick={handleLogout}
            className="p-2 rounded-lg hover:bg-slate-100 text-slate-500"
            aria-label={t('common.logout')}
            title={t('common.logout')}
          >
            <FiLogOut size={20} />
          </button>
        </div>
      )}
    </header>
  );
}
