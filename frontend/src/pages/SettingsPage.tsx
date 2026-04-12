import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/stores/auth.store';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';

export function SettingsPage() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-semibold text-slate-900">{t('settings.title')}</h1>
      <div className="card space-y-3">
        <h3 className="font-semibold">{t('settings.profile')}</h3>
        <div className="text-sm text-slate-600"><strong>{t('settings.name')}:</strong> {user?.firstName} {user?.lastName}</div>
        <div className="text-sm text-slate-600"><strong>{t('settings.email')}:</strong> {user?.email}</div>
        <div className="text-sm text-slate-600"><strong>{t('settings.role')}:</strong> <span className={user?.role === 'admin' ? 'badge-admin' : 'badge-user'}>{user?.role}</span></div>
      </div>
      <div className="card">
        <h3 className="font-semibold mb-3">{t('common.language')}</h3>
        <LanguageSwitcher variant="inline" />
      </div>
    </div>
  );
}
