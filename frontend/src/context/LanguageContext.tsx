import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

/** Preferred language for assistant answers. */
export type ResponseLanguage = 'en' | 'vi';

export const LANGUAGE_OPTIONS: { value: ResponseLanguage; label: string; sub: string }[] = [
  { value: 'en', label: 'English', sub: 'Always answer in English' },
  { value: 'vi', label: 'Tiếng Việt', sub: 'Luôn trả lời bằng tiếng Việt' },
];

const DEFAULT_LANGUAGE: ResponseLanguage = 'en';

type LanguageContextValue = {
  language: ResponseLanguage;
  setLanguage: (l: ResponseLanguage) => void;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

const STORAGE_KEY = 'responseLanguage';

function readInitial(): ResponseLanguage {
  if (typeof window === 'undefined') return DEFAULT_LANGUAGE;
  try {
    const s = window.localStorage.getItem(STORAGE_KEY);
    // ``en``/``vi`` only now — any legacy value (e.g. ``auto``) falls back.
    if (s === 'en' || s === 'vi') return s;
  } catch {
    // localStorage disabled — fall back to default
  }
  return DEFAULT_LANGUAGE;
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<ResponseLanguage>(readInitial);

  const setLanguage = useCallback((l: ResponseLanguage) => {
    setLanguageState(l);
    try {
      window.localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* localStorage disabled — preference just won't persist */
    }
  }, []);

  const value = useMemo(() => ({ language, setLanguage }), [language, setLanguage]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error('useLanguage must be used within LanguageProvider');
  return ctx;
}
