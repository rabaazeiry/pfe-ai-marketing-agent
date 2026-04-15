import type { ReactNode } from 'react';
import { FiAlertTriangle, FiInbox, FiLoader } from 'react-icons/fi';

type StateViewProps = {
  variant: 'loading' | 'empty' | 'error';
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
};

const BUBBLE: Record<StateViewProps['variant'], string> = {
  loading: 'bg-brand-50 text-brand-600',
  empty: 'bg-slate-100 text-slate-500',
  error: 'bg-red-50 text-red-600'
};

export function StateView({ variant, title, children, action }: StateViewProps) {
  const Icon = variant === 'loading' ? FiLoader : variant === 'empty' ? FiInbox : FiAlertTriangle;

  return (
    <div className="flex flex-col items-center justify-center text-center py-10 gap-3 animate-fade-in">
      <span className={`inline-flex h-12 w-12 items-center justify-center rounded-full ${BUBBLE[variant]}`}>
        <Icon className={`w-6 h-6 ${variant === 'loading' ? 'animate-spin' : ''}`} />
      </span>
      {title && <div className="text-sm font-semibold text-slate-800">{title}</div>}
      {children && <div className="text-xs text-slate-500 max-w-sm leading-relaxed">{children}</div>}
      {action && <div className="pt-1">{action}</div>}
    </div>
  );
}
