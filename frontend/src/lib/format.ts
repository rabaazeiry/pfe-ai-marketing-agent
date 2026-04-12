export function formatNumber(n: number | undefined | null, lang: string): string {
  if (n === null || n === undefined) return '—';
  try {
    return new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(n);
  } catch {
    return String(n);
  }
}

export function formatDate(date: string | Date | undefined | null, lang: string): string {
  if (!date) return '—';
  try {
    return new Intl.DateTimeFormat(lang, { dateStyle: 'medium' }).format(new Date(date));
  } catch {
    return String(date);
  }
}
