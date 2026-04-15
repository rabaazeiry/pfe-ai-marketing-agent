import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FiCheckCircle } from 'react-icons/fi';
import { useAuthStore } from '@/stores/auth.store';
import { useUpdateProfile } from './hooks';

export function ProfileForm() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const mutation = useUpdateProfile();

  const [firstName, setFirstName] = useState(user?.firstName ?? '');
  const [lastName, setLastName] = useState(user?.lastName ?? '');
  const [email, setEmail] = useState(user?.email ?? '');

  useEffect(() => {
    if (!user) return;
    setFirstName(user.firstName);
    setLastName(user.lastName);
    setEmail(user.email);
  }, [user]);

  const isDirty =
    firstName.trim() !== (user?.firstName ?? '') ||
    lastName.trim() !== (user?.lastName ?? '') ||
    email.trim() !== (user?.email ?? '');

  const errorMessage =
    (mutation.error as { response?: { data?: { message?: string } } } | null)?.response?.data
      ?.message ?? t('settings.errors.generic');

  return (
    <form
      className="card space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!isDirty || mutation.isPending) return;
        mutation.mutate({
          firstName: firstName.trim(),
          lastName: lastName.trim(),
          email: email.trim()
        });
      }}
    >
      <div>
        <h3 className="font-semibold">{t('settings.profile')}</h3>
        <p className="text-sm text-slate-500 mt-1">{t('settings.profileSubtitle')}</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="text-sm text-slate-600">{t('auth.firstName')}</span>
          <input
            className="input mt-1"
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            required
            autoComplete="given-name"
          />
        </label>
        <label className="block">
          <span className="text-sm text-slate-600">{t('auth.lastName')}</span>
          <input
            className="input mt-1"
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
            required
            autoComplete="family-name"
          />
        </label>
      </div>

      <label className="block">
        <span className="text-sm text-slate-600">{t('settings.email')}</span>
        <input
          className="input mt-1"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
        />
      </label>

      {mutation.isError && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {errorMessage}
        </div>
      )}

      {mutation.isSuccess && !isDirty && (
        <div className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 flex items-center gap-2">
          <FiCheckCircle /> {t('settings.profileSaved')}
        </div>
      )}

      <div className="flex justify-end">
        <button
          type="submit"
          className="btn-primary"
          disabled={!isDirty || mutation.isPending}
        >
          {mutation.isPending ? t('common.loading') : t('common.save')}
        </button>
      </div>
    </form>
  );
}
