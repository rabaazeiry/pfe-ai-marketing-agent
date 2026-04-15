import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from 'react';
import { FiAlertTriangle, FiCheckCircle, FiInfo, FiX } from 'react-icons/fi';

type ToastVariant = 'success' | 'error' | 'info';

type ToastInput = {
  title?: string;
  message: string;
  variant?: ToastVariant;
  durationMs?: number;
};

type Toast = Required<Omit<ToastInput, 'title'>> & {
  id: number;
  title?: string;
};

type ToastContextValue = {
  show: (t: ToastInput) => number;
  success: (message: string, title?: string) => number;
  error: (message: string, title?: string) => number;
  info: (message: string, title?: string) => number;
  dismiss: (id: number) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

const DEFAULT_DURATION = 3500;

const VARIANT_STYLES: Record<ToastVariant, { ring: string; bar: string; icon: ReactNode; iconTone: string }> = {
  success: {
    ring: 'ring-emerald-200',
    bar: 'bg-emerald-500',
    icon: <FiCheckCircle />,
    iconTone: 'text-emerald-600 bg-emerald-50'
  },
  error: {
    ring: 'ring-red-200',
    bar: 'bg-red-500',
    icon: <FiAlertTriangle />,
    iconTone: 'text-red-600 bg-red-50'
  },
  info: {
    ring: 'ring-slate-200',
    bar: 'bg-brand-500',
    icon: <FiInfo />,
    iconTone: 'text-brand-600 bg-brand-50'
  }
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<number, number>>(new Map());
  const idRef = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const handle = timers.current.get(id);
    if (handle) {
      window.clearTimeout(handle);
      timers.current.delete(id);
    }
  }, []);

  const show = useCallback(
    (input: ToastInput) => {
      idRef.current += 1;
      const id = idRef.current;
      const toast: Toast = {
        id,
        title: input.title,
        message: input.message,
        variant: input.variant ?? 'info',
        durationMs: input.durationMs ?? DEFAULT_DURATION
      };
      setToasts((prev) => [...prev, toast]);
      if (toast.durationMs > 0) {
        const handle = window.setTimeout(() => dismiss(id), toast.durationMs);
        timers.current.set(id, handle);
      }
      return id;
    },
    [dismiss]
  );

  useEffect(
    () => () => {
      timers.current.forEach((h) => window.clearTimeout(h));
      timers.current.clear();
    },
    []
  );

  const value = useMemo<ToastContextValue>(
    () => ({
      show,
      dismiss,
      success: (message, title) => show({ message, title, variant: 'success' }),
      error: (message, title) => show({ message, title, variant: 'error' }),
      info: (message, title) => show({ message, title, variant: 'info' })
    }),
    [show, dismiss]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}

function ToastViewport({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  if (toasts.length === 0) return null;
  return (
    <div
      className="fixed bottom-4 end-4 z-[60] flex w-full max-w-sm flex-col gap-2 pointer-events-none"
      role="region"
      aria-label="Notifications"
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const styles = VARIANT_STYLES[toast.variant];
  return (
    <div
      role={toast.variant === 'error' ? 'alert' : 'status'}
      className={`pointer-events-auto relative overflow-hidden rounded-xl bg-white shadow-soft ring-1 ${styles.ring} animate-toast-in`}
    >
      <div className={`absolute inset-y-0 start-0 w-1 ${styles.bar}`} aria-hidden />
      <div className="flex items-start gap-3 p-3 ps-4">
        <span className={`mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${styles.iconTone}`}>
          {styles.icon}
        </span>
        <div className="min-w-0 flex-1">
          {toast.title && <div className="text-sm font-semibold text-slate-900">{toast.title}</div>}
          <div className="text-sm text-slate-600 break-words">{toast.message}</div>
        </div>
        <button
          type="button"
          onClick={() => onDismiss(toast.id)}
          className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
          aria-label="Dismiss"
        >
          <FiX />
        </button>
      </div>
    </div>
  );
}
