import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FiCheckCircle } from 'react-icons/fi';
import { useChangePassword } from './hooks';

const MIN_LENGTH = 6;

export function PasswordForm() {
  const { t } = useTranslation();
  const mutation = useChangePassword();

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);

  const reset = () => {
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
  };

  const serverError =
    (mutation.error as { response?: { data?: { message?: string } } } | null)?.response?.data
      ?.message ?? (mutation.isError ? t('settings.errors.generic') : null);

  const canSubmit =
    !mutation.isPending &&
    Boolean(currentPassword) &&
    Boolean(newPassword) &&
    Boolean(confirmPassword);

  return (
    <form
      className="card space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        setLocalError(null);

        if (newPassword.length < MIN_LENGTH) {
          setLocalError(t('settings.errors.passwordTooShort', { min: MIN_LENGTH }));
          return;
        }
        if (newPassword !== confirmPassword) {
          setLocalError(t('settings.errors.passwordMismatch'));
          return;
        }
        if (currentPassword === newPassword) {
          setLocalError(t('settings.errors.passwordSame'));
          return;
        }

        mutation.mutate({ currentPassword, newPassword }, { onSuccess: reset });
      }}
    >
      <div>
        <h3 className="font-semibold text-slate-900">{t('settings.password.title')}</h3>
        <p className="text-sm text-slate-500 mt-1">{t('settings.password.subtitle')}</p>
      </div>

      <label className="block">
        <span className="block text-xs font-medium text-slate-600 mb-1">
          {t('settings.password.current')}
        </span>
        <input
          className="input"
          type="password"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
          required
          autoComplete="current-password"
        />
      </label>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <label className="block">
          <span className="block text-xs font-medium text-slate-600 mb-1">
            {t('settings.password.new')}
          </span>
          <input
            className="input"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            minLength={MIN_LENGTH}
            autoComplete="new-password"
          />
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-slate-600 mb-1">
            {t('settings.password.confirm')}
          </span>
          <input
            className="input"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            minLength={MIN_LENGTH}
            autoComplete="new-password"
          />
        </label>
      </div>

      {(localError || serverError) && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {localError ?? serverError}
        </div>
      )}

      {mutation.isSuccess && !currentPassword && !newPassword && (
        <div className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 flex items-center gap-2">
          <FiCheckCircle /> {t('settings.password.updated')}
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-4 border-t border-slate-100">
        <button type="submit" className="btn-primary" disabled={!canSubmit}>
          {mutation.isPending ? t('common.loading') : t('settings.password.submit')}
        </button>
      </div>
    </form>
  );
}
