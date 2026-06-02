import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

/** Preferred language for assistant answers. ``auto`` lets the backend reply
 *  in whatever language the question was asked in. */
export type ResponseLanguage = 'auto' | 'en' | 'vi';

export const LANGUAGE_OPTIONS: { value: ResponseLanguage; label: string; sub: string }[] = [
  { value: 'auto', label: 'Auto', sub: 'Match the language of your question' },
  { value: 'en', label: 'English', sub: 'Always answer in English' },
  { value: 'vi', label: 'Tiếng Việt', sub: 'Luôn trả lời bằng tiếng Việt' },
];

type LanguageContextValue = {
  language: ResponseLanguage;
  setLanguage: (l: ResponseLanguage) => void;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

const STORAGE_KEY = 'responseLanguage';

function readInitial(): ResponseLanguage {
  if (typeof window === 'undefined') return 'auto';
  try {
    const s = window.localStorage.getItem(STORAGE_KEY);
    if (s === 'auto' || s === 'en' || s === 'vi') return s;
  } catch {
    // localStorage disabled — fall back to default
  }
  return 'auto';
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
