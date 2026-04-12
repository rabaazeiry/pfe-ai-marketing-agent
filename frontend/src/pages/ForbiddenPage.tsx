import { FiLock } from 'react-icons/fi';
import { Link } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';

export function ForbiddenPage() {
  const { t } = useTranslation();
  return (
    <div className="min-h-[60vh] grid place-items-center">
      <div className="text-center">
        <div className="w-14 h-14 rounded-full bg-red-50 text-red-600 grid place-items-center mx-auto">
          <FiLock size={24} />
        </div>
        <h1 className="text-2xl font-semibold mt-4">{t('errors.forbidden.title')}</h1>
        <p className="text-slate-500 mt-1">{t('errors.forbidden.body')}</p>
        <Link to="/" className="btn-primary mt-6 inline-flex">{t('errors.forbidden.back')}</Link>
      </div>
    </div>
  );
}
