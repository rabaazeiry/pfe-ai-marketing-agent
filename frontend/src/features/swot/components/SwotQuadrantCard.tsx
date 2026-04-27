import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { FiAlertOctagon, FiTarget, FiTrendingDown, FiTrendingUp } from 'react-icons/fi';
import type { SwotQuadrantKey, SwotSource } from '../types';

type Props = {
  quadrant: SwotQuadrantKey;
  text: string;
  source?: SwotSource;
};

const ICON: Record<SwotQuadrantKey, ReactNode> = {
  strengths    : <FiTrendingUp />,
  weaknesses   : <FiTrendingDown />,
  opportunities: <FiTarget />,
  threats      : <FiAlertOctagon />
};

const TONE: Record<SwotQuadrantKey, string> = {
  strengths    : 'bg-emerald-50 text-emerald-700 ring-emerald-100',
  weaknesses   : 'bg-red-50 text-red-700 ring-red-100',
  opportunities: 'bg-sky-50 text-sky-700 ring-sky-100',
  threats      : 'bg-amber-50 text-amber-700 ring-amber-100'
};

export function SwotQuadrantCard({ quadrant, text, source }: Props) {
  const { t } = useTranslation();
  const isFallback = source?.type === 'fallback';

  return (
    <div className={`rounded-xl ring-1 ${TONE[quadrant]} p-4 flex flex-col gap-2 min-h-[140px]`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-white/70">
            {ICON[quadrant]}
          </span>
          <div className="text-sm font-semibold">
            {t(`projects.detail.swot.quadrants.${quadrant}`)}
          </div>
        </div>
        {isFallback && (
          <span
            className="text-[10px] uppercase tracking-wide text-slate-500 bg-white/60 rounded-full px-1.5 py-0.5"
            title={source?.reason || ''}
          >
            {t('projects.detail.swot.source.fallback')}
          </span>
        )}
      </div>
      <p className="text-sm leading-relaxed text-slate-700 flex-1">
        {text?.trim() || t('projects.detail.swot.source.empty')}
      </p>
    </div>
  );
}
