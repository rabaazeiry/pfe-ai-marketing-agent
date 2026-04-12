import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { useTranslation, Trans } from 'react-i18next';
import { FiMail, FiLock } from 'react-icons/fi';
import { login, register } from '@/features/auth/api';
import { useAuthStore } from '@/stores/auth.store';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { useLangEffect } from '@/i18n/useLangEffect';

export function LoginPage() {
  useLangEffect();
  const { t } = useTranslation();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const navigate = useNavigate();
  const setSession = useAuthStore((s) => s.setSession);

  const mutation = useMutation({
    mutationFn: async () => {
      if (mode === 'login') return login({ email, password });
      return register({ email, password, firstName, lastName });
    },
    onSuccess: (data) => {
      setSession({ token: data.token, user: data.user });
      navigate({ to: '/' });
    }
  });

  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      <div className="hidden lg:flex flex-col justify-between p-10 bg-gradient-to-br from-brand-600 to-brand-800 text-white">
        <div className="font-semibold flex items-center gap-2">
          <span className="w-9 h-9 rounded-lg bg-white/10 grid place-items-center">PM</span>
          PFE Marketing
        </div>
        <div>
          <h1 className="text-4xl font-semibold leading-tight">
            <Trans i18nKey="auth.brand.tagline" components={{ br: <br /> }} />
          </h1>
          <p className="mt-4 text-white/70 max-w-sm">{t('auth.brand.body')}</p>
        </div>
        <div className="text-xs text-white/50">© {new Date().getFullYear()} PFE Marketing</div>
      </div>

      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-md card">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold text-slate-900">
                {mode === 'login' ? t('auth.login.title') : t('auth.register.title')}
              </h2>
              <p className="text-sm text-slate-500 mt-1">
                {mode === 'login' ? t('auth.login.subtitle') : t('auth.register.subtitle')}
              </p>
            </div>
            <LanguageSwitcher />
          </div>

          <form
            className="mt-6 space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              mutation.mutate();
            }}
          >
            {mode === 'register' && (
              <div className="grid grid-cols-2 gap-3">
                <input className="input" placeholder={t('auth.firstName')} value={firstName} onChange={(e) => setFirstName(e.target.value)} required />
                <input className="input" placeholder={t('auth.lastName')} value={lastName} onChange={(e) => setLastName(e.target.value)} required />
              </div>
            )}
            <div className="relative">
              <FiMail className="absolute start-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                className="input ps-9"
                type="email"
                placeholder={t('auth.email')}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="relative">
              <FiLock className="absolute start-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                className="input ps-9"
                type="password"
                placeholder={t('auth.password')}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
              />
            </div>

            {mutation.isError && (
              <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                {(mutation.error as any)?.response?.data?.message ?? t('auth.error')}
              </div>
            )}

            <button type="submit" className="btn-primary w-full" disabled={mutation.isPending}>
              {mutation.isPending ? '...' : mode === 'login' ? t('auth.login.submit') : t('auth.register.submit')}
            </button>
          </form>

          <div className="mt-4 text-sm text-slate-500 text-center">
            {mode === 'login' ? t('auth.switch.toRegister') : t('auth.switch.toLogin')}{' '}
            <button
              type="button"
              className="text-brand-600 font-medium hover:underline"
              onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
            >
              {mode === 'login' ? t('auth.switch.registerCta') : t('auth.switch.loginCta')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
