import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { FiGlobe, FiCheck } from 'react-icons/fi';
import clsx from 'clsx';
import { SUPPORTED_LANGS, type Lang } from '@/i18n';

const LABELS: Record<Lang, { label: string; flag: string }> = {
  fr: { label: 'Français', flag: '🇫🇷' },
  ar: { label: 'العربية',   flag: '🇹🇳' },
  en: { label: 'English',  flag: '🇬🇧' }
};

export function LanguageSwitcher({ variant = 'button' }: { variant?: 'button' | 'inline' }) {
  const { i18n, t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  const current = (i18n.language.split('-')[0] as Lang) in LABELS
    ? (i18n.language.split('-')[0] as Lang)
    : 'fr';

  if (variant === 'inline') {
    return (
      <div className="flex items-center gap-2">
        <FiGlobe className="text-slate-400" />
        <select
          className="input max-w-[10rem] py-1.5"
          value={current}
          onChange={(e) => i18n.changeLanguage(e.target.value)}
          aria-label={t('common.language')}
        >
          {SUPPORTED_LANGS.map((l) => (
            <option key={l} value={l}>
              {LABELS[l].flag} {LABELS[l].label}
            </option>
          ))}
        </select>
      </div>
    );
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        className="p-2 rounded-lg hover:bg-slate-100 text-slate-600 inline-flex items-center gap-1"
        onClick={() => setOpen((o) => !o)}
        aria-label={t('common.language')}
        title={t('common.language')}
      >
        <FiGlobe size={20} />
        <span className="hidden sm:inline text-sm">{LABELS[current].flag}</span>
      </button>

      {open && (
        <ul
          className={clsx(
            'absolute mt-2 w-44 bg-white border border-slate-200 rounded-lg shadow-soft py-1 z-50',
            'end-0'
          )}
        >
          {SUPPORTED_LANGS.map((l) => (
            <li key={l}>
              <button
                type="button"
                className="w-full px-3 py-2 text-sm text-start hover:bg-slate-50 flex items-center justify-between gap-2"
                onClick={() => {
                  i18n.changeLanguage(l);
                  setOpen(false);
                }}
              >
                <span>
                  {LABELS[l].flag} {LABELS[l].label}
                </span>
                {current === l && <FiCheck className="text-brand-600" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
