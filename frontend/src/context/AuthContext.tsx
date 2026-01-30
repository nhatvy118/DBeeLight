import { createContext, useCallback, useContext, useEffect, useState } from 'react';

export type AuthUser = {
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

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const loadMe = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await fetch('/api/auth/me', { method: 'GET', credentials: 'include' });
      const data = (await res.json()) as { authenticated: boolean; user?: AuthUser | null };
      setUser(data.authenticated ? (data.user ?? null) : null);
    } catch {
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadMe();
  }, [loadMe]);

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
