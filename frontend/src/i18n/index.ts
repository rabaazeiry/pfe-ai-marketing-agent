import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import fr from './locales/fr/common.json';
import ar from './locales/ar/common.json';
import en from './locales/en/common.json';

export const SUPPORTED_LANGS = ['fr', 'ar', 'en'] as const;
export type Lang = (typeof SUPPORTED_LANGS)[number];
export const RTL_LANGS: Lang[] = ['ar'];
export const DEFAULT_LANG: Lang = 'fr';

export function isRtl(lang: string): boolean {
  return RTL_LANGS.includes(lang as Lang);
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      fr: { common: fr },
      ar: { common: ar },
      en: { common: en }
    },
    fallbackLng: DEFAULT_LANG,
    supportedLngs: SUPPORTED_LANGS as unknown as string[],
    nonExplicitSupportedLngs: true,
    ns: ['common'],
    defaultNS: 'common',
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator', 'htmlTag'],
      caches: ['localStorage'],
      lookupLocalStorage: 'i18nextLng'
    },
    returnNull: false
  });

export default i18n;
