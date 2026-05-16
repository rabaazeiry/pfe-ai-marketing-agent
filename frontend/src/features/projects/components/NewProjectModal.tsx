import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FiLoader, FiSearch, FiX, FiZap } from 'react-icons/fi';
import { suggestProjectName } from '../api';

export type NewProjectFormValues = {
  businessIdea: string;
  marketCategory: string;
  targetCountry: string;
  name?: string;
};

type Props = {
  open: boolean;
  onClose: () => void;
  onSubmit: (values: NewProjectFormValues) => Promise<void> | void;
  isSubmitting?: boolean;
  errorMessage?: string | null;
};

const MIN_IDEA_LENGTH = 10;

export function NewProjectModal({ open, onClose, onSubmit, isSubmitting, errorMessage }: Props) {
  const { t } = useTranslation();

  const [businessIdea,  setBusinessIdea]  = useState('');
  const [industry,      setIndustry]      = useState('');
  const [targetCountry, setTargetCountry] = useState('Tunisie');
  const [projectName,   setProjectName]   = useState('');
  const [isDetecting,   setIsDetecting]   = useState(false);
  const [isSuggesting,  setIsSuggesting]  = useState(false);
  const [localError,    setLocalError]    = useState<string | null>(null);

  const firstFieldRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!open) {
      setBusinessIdea('');
      setIndustry('');
      setTargetCountry('Tunisie');
      setProjectName('');
      setIsDetecting(false);
      setIsSuggesting(false);
      setLocalError(null);
      return;
    }
    const id = window.setTimeout(() => firstFieldRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isLocked) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, isSubmitting, isDetecting, isSuggesting, onClose]);

  if (!open) return null;

  const ideaReady = businessIdea.trim().length >= MIN_IDEA_LENGTH;
  const isLocked  = isSubmitting || isDetecting || isSuggesting;

  // ── Detect industry only ──────────────────────────────────────────────────
  const handleDetect = async () => {
    if (!ideaReady || isLocked) return;
    setIsDetecting(true);
    setLocalError(null);
    try {
      const result = await suggestProjectName({
        businessIdea:   businessIdea.trim(),
        marketCategory: '',                          // empty → LLM auto-detects
        targetCountry:  targetCountry.trim() || 'Tunisie',
      });
      setIndustry(result.industry);
    } catch {
      setLocalError('Impossible de détecter l\'industrie. Saisissez-la manuellement.');
    } finally {
      setIsDetecting(false);
    }
  };

  // ── Suggest project name (auto-detects industry first if needed) ──────────
  const handleSuggestName = async () => {
    if (!ideaReady || isLocked) return;
    setIsSuggesting(true);
    setLocalError(null);
    try {
      const cat = industry.trim();
      const result = await suggestProjectName({
        businessIdea:   businessIdea.trim(),
        marketCategory: cat,                         // empty if user hasn't typed yet
        targetCountry:  targetCountry.trim() || 'Tunisie',
      });
      // If industry was empty, fill it from what Groq detected
      if (!cat && result.industry) {
        setIndustry(result.industry);
      }
      setProjectName(result.name);
    } catch {
      setLocalError('Impossible de générer un nom. Vous pouvez en saisir un manuellement.');
    } finally {
      setIsSuggesting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedIdea = businessIdea.trim();
    if (trimmedIdea.length < MIN_IDEA_LENGTH) {
      setLocalError(t('projects.create.errors.ideaTooShort', { min: MIN_IDEA_LENGTH }));
      return;
    }
    if (!industry.trim()) {
      setLocalError('Veuillez saisir ou détecter une industrie.');
      return;
    }
    setLocalError(null);
    await onSubmit({
      businessIdea:   trimmedIdea,
      marketCategory: industry.trim(),
      targetCountry:  targetCountry.trim() || 'Tunisie',
      name:           projectName.trim() || undefined,
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
        if (e.target === e.currentTarget && !isLocked) onClose();
      }}
    >
      <div className="w-full max-w-lg rounded-xl bg-white shadow-soft border border-slate-100">
        {/* Header */}
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
            disabled={isLocked}
            aria-label={t('common.close')}
          >
            <FiX />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-5 pb-5 pt-4 space-y-4">

          {/* Business Idea */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="np-idea">
              {t('projects.create.fields.idea')}
            </label>
            <textarea
              id="np-idea"
              ref={firstFieldRef}
              className="input min-h-[88px] resize-y"
              placeholder={t('projects.create.placeholders.idea')}
              value={businessIdea}
              onChange={(e) => setBusinessIdea(e.target.value)}
              disabled={isLocked}
              required
              minLength={MIN_IDEA_LENGTH}
            />
            <p className="mt-1 text-[11px] text-slate-400">
              {t('projects.create.hints.ideaMin', { min: MIN_IDEA_LENGTH })}
            </p>
          </div>

          {/* Industry — free text + Détecter */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="np-industry">
              Industrie <span className="text-red-400">*</span>
            </label>
            <div className="flex gap-2">
              <input
                id="np-industry"
                className="input flex-1"
                placeholder={isDetecting ? 'Détection en cours…' : 'Ex: Sport & Fitness, Immobilier, Education…'}
                value={industry}
                onChange={(e) => setIndustry(e.target.value)}
                disabled={isLocked}
                required
              />
              <AIButton
                onClick={handleDetect}
                disabled={!ideaReady || isLocked}
                loading={isDetecting}
                icon={<FiSearch className="h-3.5 w-3.5" />}
                label="Détecter"
                loadingLabel="Détection…"
                title={ideaReady ? 'Détecter l\'industrie avec Groq' : 'Décrivez d\'abord votre idée'}
              />
            </div>
            <p className="mt-1 text-[11px] text-slate-400">
              Saisissez votre industrie ou laissez Groq la détecter automatiquement.
            </p>
          </div>

          {/* Target Country */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="np-country">
              Pays cible{' '}
              <span className="text-slate-400 font-normal">(modifiable)</span>
            </label>
            <input
              id="np-country"
              className="input"
              placeholder="Tunisie"
              value={targetCountry}
              onChange={(e) => setTargetCountry(e.target.value)}
              disabled={isLocked}
            />
          </div>

          {/* Project Name + Suggérer */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1" htmlFor="np-name">
              Nom du projet{' '}
              <span className="text-slate-400 font-normal">(optionnel)</span>
            </label>
            <div className="flex gap-2">
              <input
                id="np-name"
                className="input flex-1"
                placeholder={isSuggesting ? 'Génération en cours…' : 'Ex: Maison de Mode Tunis'}
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                disabled={isLocked}
              />
              <AIButton
                onClick={handleSuggestName}
                disabled={!ideaReady || isLocked}
                loading={isSuggesting}
                icon={<FiZap className="h-3.5 w-3.5" />}
                label="Suggérer"
                loadingLabel="Génération…"
                title={
                  !ideaReady
                    ? 'Décrivez d\'abord votre idée'
                    : !industry.trim()
                      ? 'Suggérer un nom et détecter l\'industrie'
                      : 'Générer un nom avec Groq'
                }
              />
            </div>
            <p className="mt-1 text-[11px] text-slate-400">
              {industry.trim()
                ? 'Laissez vide pour laisser l\'IA générer automatiquement.'
                : 'Cliquez Suggérer pour remplir le nom ET détecter l\'industrie en une fois.'}
            </p>
          </div>

          {/* Error */}
          {errorToShow && (
            <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 border border-red-100">
              {errorToShow}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-2 pt-2">
            <button type="button" className="btn-ghost" onClick={onClose} disabled={isLocked}>
              {t('common.cancel')}
            </button>
            <button type="submit" className="btn-primary" disabled={isLocked}>
              {isSubmitting ? t('common.loading') : t('projects.create.submit')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Shared AI action button ───────────────────────────────────────────────────
function AIButton({
  onClick, disabled, loading, icon, label, loadingLabel, title,
}: {
  onClick: () => void;
  disabled: boolean;
  loading: boolean;
  icon: React.ReactNode;
  label: string;
  loadingLabel: string;
  title: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-amber-50 hover:border-amber-200 hover:text-amber-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
    >
      {loading
        ? <FiLoader className="animate-spin h-3.5 w-3.5" />
        : icon}
      {loading ? loadingLabel : label}
    </button>
  );
}
