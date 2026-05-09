import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';

export type AuthUser = {
  // Stable Google identifier — used for cross-tab identity comparison.
  sub?: string;
  name?: string;
  email?: string;
  picture?: string;
};

type AuthContextValue = {
  user: AuthUser | null;
  isLoading: boolean;
  setUser: (u: AuthUser | null) => void;
  loadMe: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

// Cross-tab sync channel. Cookies are shared across tabs of the same origin,
// so logging in/out in one tab silently changes the identity of every other
// open tab. We detect that and reload, instead of letting the stale UI keep
// firing API calls under a different identity.
const AUTH_CHANNEL = 'auth-sync';
const STORAGE_KEY_SUB = 'auth.sub';
const STORAGE_KEY_BUMP = 'auth.bump';

function postAuthChange(sub: string | null) {
  if (typeof BroadcastChannel !== 'undefined') {
    try {
      const ch = new BroadcastChannel(AUTH_CHANNEL);
      ch.postMessage({ sub });
      ch.close();
      return;
    } catch {
      // fall through to localStorage fallback
    }
  }
  try {
    localStorage.setItem(STORAGE_KEY_SUB, sub ?? '');
    localStorage.setItem(STORAGE_KEY_BUMP, String(Date.now()));
  } catch {
    // storage may be disabled — give up silently
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  // Mirrors the latest sub we believe is authenticated. Kept in a ref because
  // the visibility/broadcast handlers must read the freshest value without
  // re-subscribing on every render.
  const lastSubRef = useRef<string | null>(null);

  const broadcastIfChanged = useCallback((nextSub: string | null) => {
    if (nextSub === lastSubRef.current) return;
    lastSubRef.current = nextSub;
    postAuthChange(nextSub);
  }, []);

  const loadMe = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await fetch('/api/auth/me', {
        method: 'GET',
        credentials: 'include',
      });
      const data = (await res.json()) as {
        authenticated: boolean;
        user?: AuthUser | null;
      };
      const next = data.authenticated ? data.user ?? null : null;
      setUserState(next);
      broadcastIfChanged(next?.sub ?? null);
    } catch {
      setUserState(null);
      broadcastIfChanged(null);
    } finally {
      setIsLoading(false);
    }
  }, [broadcastIfChanged]);

  // Wrap setUser so explicit local mutations (e.g. logout button) broadcast too.
  const setUser = useCallback(
    (u: AuthUser | null) => {
      setUserState(u);
      broadcastIfChanged(u?.sub ?? null);
    },
    [broadcastIfChanged],
  );

  useEffect(() => {
    void loadMe();
  }, [loadMe]);

  // (#1) Re-check cookie identity each time the tab becomes visible.
  // Catches: user opened another tab, logged in as a different account, then
  // came back here. Their cookie has been swapped out from under us.
  useEffect(() => {
    const onVisibility = async () => {
      if (document.visibilityState !== 'visible') return;
      try {
        const res = await fetch('/api/auth/me', { credentials: 'include' });
        const data = (await res.json()) as {
          authenticated: boolean;
          user?: AuthUser | null;
        };
        const cookieSub = (data.authenticated ? data.user?.sub : null) ?? null;
        if (cookieSub !== lastSubRef.current) {
          window.location.reload();
        }
      } catch {
        // network blip — ignore, will retry next focus
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

  // (#2) Live cross-tab signal. When any tab announces a sub change, every
  // other tab whose state disagrees reloads immediately — no need to wait
  // for the user to refocus that tab.
  useEffect(() => {
    const handle = (incomingSub: string | null) => {
      if (incomingSub !== lastSubRef.current) {
        window.location.reload();
      }
    };

    if (typeof BroadcastChannel !== 'undefined') {
      let channel: BroadcastChannel | null = null;
      try {
        channel = new BroadcastChannel(AUTH_CHANNEL);
        channel.onmessage = (e: MessageEvent) => {
          const sub = (e.data && typeof e.data === 'object' ? e.data.sub : null) ?? null;
          handle(sub);
        };
      } catch {
        channel = null;
      }
      if (channel) {
        const ch = channel;
        return () => {
          try {
            ch.close();
          } catch {
            /* noop */
          }
        };
      }
    }

    // Fallback for environments without BroadcastChannel (older Safari, etc.)
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY_BUMP) return;
      const raw = localStorage.getItem(STORAGE_KEY_SUB);
      const sub = raw && raw.length > 0 ? raw : null;
      handle(sub);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, setUser, loadMe }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
