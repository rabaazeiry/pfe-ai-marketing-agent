import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/stores/auth.store';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { ProfileForm } from '@/features/settings/ProfileForm';
import { PasswordForm } from '@/features/settings/PasswordForm';

export function SettingsPage() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-semibold text-slate-900">{t('settings.title')}</h1>

      <div className="card space-y-2">
        <h3 className="font-semibold">{t('settings.account')}</h3>
        <div className="text-sm text-slate-600">
          <strong>{t('settings.role')}:</strong>{' '}
          <span className={user?.role === 'admin' ? 'badge-admin' : 'badge-user'}>
            {user?.role}
          </span>
        </div>
      </div>

      <ProfileForm />
      <PasswordForm />

      <div className="card">
        <h3 className="font-semibold mb-3">{t('common.language')}</h3>
        <LanguageSwitcher variant="inline" />
      </div>
    </div>
  );
}
