import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { isRtl } from './index';

export function useLangEffect() {
  const { i18n } = useTranslation();

  useEffect(() => {
    const apply = (lng: string) => {
      const base = lng.split('-')[0];
      document.documentElement.lang = base;
      document.documentElement.dir = isRtl(base) ? 'rtl' : 'ltr';
    };

    apply(i18n.language);
    i18n.on('languageChanged', apply);
    return () => {
      i18n.off('languageChanged', apply);
    };
  }, [i18n]);
}
