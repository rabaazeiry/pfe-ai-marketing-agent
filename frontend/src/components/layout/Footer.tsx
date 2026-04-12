import { FiGithub, FiHeart } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';

const YEAR = new Date().getFullYear();

export function Footer() {
  const { t } = useTranslation();
  const system = t('footer.system');

  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="px-6 py-4 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-slate-500">
        <div className="flex items-center gap-2">
          <span className="w-6 h-6 rounded bg-brand-600 text-white grid place-items-center text-[10px] font-bold">
            PM
          </span>
          <span className="font-medium text-slate-700">{system}</span>
          <span className="hidden sm:inline">·</span>
          <span>v0.1.0</span>
        </div>

        <div className="flex items-center gap-4">
          <span>{t('footer.copyright', { year: YEAR, system })}</span>
          <a
            href="https://github.com/rabaazeiry"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 hover:text-slate-800"
          >
            <FiGithub /> GitHub
          </a>
          <span className="inline-flex items-center gap-1">
            {t('footer.builtBy')} <FiHeart className="text-red-500" /> Rabaa Zeiri
          </span>
        </div>
      </div>
    </footer>
  );
}
