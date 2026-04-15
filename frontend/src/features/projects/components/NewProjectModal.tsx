import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FiX } from 'react-icons/fi';

export type NewProjectFormValues = {
  businessIdea: string;
  marketCategory: string;
};

type Props = {
  open: boolean;
  onClose: () => void;
  onSubmit: (values: NewProjectFormValues) => Promise<void> | void;
  isSubmitting?: boolean;
  errorMessage?: string | null;
};

const MIN_IDEA_LENGTH = 10;
const DEFAULT_CATEGORY = 'General';

export function NewProjectModal({ open, onClose, onSubmit, isSubmitting, errorMessage }: Props) {
  const { t } = useTranslation();
  const [businessIdea, setBusinessIdea] = useState('');
  const [marketCategory, setMarketCategory] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);
  const firstFieldRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!open) {
      setBusinessIdea('');
      setMarketCategory('');
      setLocalError(null);
      return;
    }
    const id = window.setTimeout(() => firstFieldRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isSubmitting) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, isSubmitting, onClose]);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedIdea = businessIdea.trim();
    if (trimmedIdea.length < MIN_IDEA_LENGTH) {
      setLocalError(t('projects.create.errors.ideaTooShort', { min: MIN_IDEA_LENGTH }));
      return;
    }
    setLocalError(null);
    await onSubmit({
      businessIdea: trimmedIdea,
      marketCategory: marketCategory.trim() || DEFAULT_CATEGORY
    });
  };

  const errorToShow = localError ?? errorMessage ?? null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="new-project-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !isSubmitting) onClose();
      }}
    >
      <div className="w-full max-w-lg rounded-xl bg-white shadow-soft border border-slate-100">
        <div className="flex items-start justify-between px-5 pt-5">
          <div>
            <h2 id="new-project-title" className="text-lg font-semibold text-slate-900">
              {t('projects.create.title')}
            </h2>
            <p className="text-xs text-slate-500">{t('projects.create.subtitle')}</p>
          </div>
          <button
            type="button"
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            onClick={onClose}
            disabled={isSubmitting}
            aria-label={t('common.close')}
          >
            <FiX />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-5 pb-5 pt-4 space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="np-idea">
              {t('projects.create.fields.idea')}
            </label>
            <textarea
              id="np-idea"
              ref={firstFieldRef}
              className="input min-h-[96px] resize-y"
              placeholder={t('projects.create.placeholders.idea')}
              value={businessIdea}
              onChange={(e) => setBusinessIdea(e.target.value)}
              disabled={isSubmitting}
              required
              minLength={MIN_IDEA_LENGTH}
            />
            <p className="mt-1 text-[11px] text-slate-400">
              {t('projects.create.hints.ideaMin', { min: MIN_IDEA_LENGTH })}
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="np-category">
              {t('projects.create.fields.category')}{' '}
              <span className="text-slate-400 font-normal">({t('projects.create.optional')})</span>
            </label>
            <input
              id="np-category"
              className="input"
              placeholder={t('projects.create.placeholders.category')}
              value={marketCategory}
              onChange={(e) => setMarketCategory(e.target.value)}
              disabled={isSubmitting}
            />
          </div>

          {errorToShow && (
            <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 border border-red-100">
              {errorToShow}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-2">
            <button type="button" className="btn-ghost" onClick={onClose} disabled={isSubmitting}>
              {t('common.cancel')}
            </button>
            <button type="submit" className="btn-primary" disabled={isSubmitting}>
              {isSubmitting ? t('common.loading') : t('projects.create.submit')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
