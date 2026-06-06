import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useAuth } from './AuthContext';
import OnboardingModal from '../components/modals/OnboardingModal';

type OnboardingContextValue = {
  /** Open the welcome / product tour (e.g. from "Help & support"). */
  open: () => void;
};

const OnboardingContext = createContext<OnboardingContextValue | null>(null);

// Per-user flag: once a user has seen (or skipped) the tour, we never auto-show
// it again on login. Keyed by the stable Google `sub` so different accounts on
// the same browser each get their own welcome.
const seenKey = (sub: string) => `onboarding.seen.${sub}`;

function hasSeen(sub: string): boolean {
  try {
    return localStorage.getItem(seenKey(sub)) === '1';
  } catch {
    return false;
  }
}

function markSeen(sub: string) {
  try {
    localStorage.setItem(seenKey(sub), '1');
  } catch {
    /* storage disabled — tour may show again next login */
  }
}

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  // Remember which user we auto-opened for so a re-render doesn't reopen it,
  // and so switching accounts re-evaluates cleanly.
  const autoCheckedFor = useRef<string | null>(null);

  // New-user auto-show: the first time we see an authenticated user who has
  // never been through the tour, open it automatically.
  useEffect(() => {
    if (isLoading) return;
    const sub = user?.sub ?? null;
    if (!sub) {
      autoCheckedFor.current = null;
      return;
    }
    if (autoCheckedFor.current === sub) return;
    autoCheckedFor.current = sub;
    if (!hasSeen(sub)) setIsOpen(true);
  }, [user, isLoading]);

  const open = useCallback(() => setIsOpen(true), []);

  const handleClose = useCallback(() => {
    setIsOpen(false);
    const sub = user?.sub;
    if (sub) markSeen(sub);
  }, [user]);

  return (
    <OnboardingContext.Provider value={{ open }}>
      {children}
      <OnboardingModal open={isOpen} onClose={handleClose} />
    </OnboardingContext.Provider>
  );
}

export function useOnboarding(): OnboardingContextValue {
  const ctx = useContext(OnboardingContext);
  if (!ctx) throw new Error('useOnboarding must be used within OnboardingProvider');
  return ctx;
}
