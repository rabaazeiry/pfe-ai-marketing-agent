import type { ReactNode } from 'react';
import { FiAlertTriangle, FiInbox, FiLoader } from 'react-icons/fi';

type StateViewProps = {
  variant: 'loading' | 'empty' | 'error';
  title?: string;
  children?: ReactNode;
};

export function StateView({ variant, title, children }: StateViewProps) {
  const Icon = variant === 'loading' ? FiLoader : variant === 'empty' ? FiInbox : FiAlertTriangle;
  const tone =
    variant === 'error'
      ? 'text-red-600'
      : variant === 'loading'
        ? 'text-brand-600'
        : 'text-slate-400';

  return (
    <div className="flex flex-col items-center justify-center text-center py-10 gap-2">
      <Icon className={`w-6 h-6 ${tone} ${variant === 'loading' ? 'animate-spin' : ''}`} />
      {title && <div className="text-sm font-medium text-slate-700">{title}</div>}
      {children && <div className="text-xs text-slate-500 max-w-sm">{children}</div>}
    </div>
  );
}
