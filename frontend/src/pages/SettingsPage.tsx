import { useTranslation } from 'react-i18next';
import { FiGlobe, FiHelpCircle, FiUser } from 'react-icons/fi';
import { useAuthStore } from '@/stores/auth.store';
import { useOnboardingStore } from '@/stores/onboarding.store';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { ProfileForm } from '@/features/settings/ProfileForm';
import { PasswordForm } from '@/features/settings/PasswordForm';

export function SettingsPage() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const startTour = useOnboardingStore((s) => s.startTour);

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">{t('settings.title')}</h1>
      </div>

      <div className="card">
        <div className="flex items-start gap-3">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
            <FiUser />
          </span>
          <div className="flex-1">
            <h3 className="font-semibold text-slate-900">{t('settings.account')}</h3>
            <div className="mt-2 flex items-center gap-2 text-sm text-slate-600">
              <span className="text-slate-500">{t('settings.role')}:</span>
              <span className={user?.role === 'admin' ? 'badge-admin' : 'badge-user'}>
                {user?.role}
              </span>
            </div>
          </div>
        </div>
      </div>

      <ProfileForm />
      <PasswordForm />

      <div className="card">
        <div className="flex items-start gap-3">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
            <FiGlobe />
          </span>
          <div className="flex-1">
            <h3 className="font-semibold text-slate-900">{t('common.language')}</h3>
            <div className="mt-3">
              <LanguageSwitcher variant="inline" />
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="flex items-start gap-3">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
            <FiHelpCircle />
          </span>
          <div className="flex-1">
            <h3 className="font-semibold text-slate-900">{t('tour.settings.title')}</h3>
            <p className="mt-1 text-sm text-slate-500">{t('tour.settings.subtitle')}</p>
            <button
              type="button"
              className="btn-ghost mt-3 inline-flex items-center gap-2"
              onClick={startTour}
            >
              <FiHelpCircle />
              <span>{t('tour.settings.replay')}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
