import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import Header from './Header';
import Sidebar from './Sidebar';

type MainLayoutProps = {
  children: ReactNode;
  currentSessionId: string | null;
  onSessionSelect: (sessionId: string | null) => void;
};

type AuthUser = {
  name?: string;
  email?: string;
  picture?: string;
};

export default function MainLayout({ children, currentSessionId, onSessionSelect }: MainLayoutProps) {
  const [path, setPath] = useState<string>(() => window.location.pathname);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    const loadMe = async () => {
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
    };
    void loadMe();
  }, []);

  // Show sidebar only if not on home page or if user is logged in
  const showSidebar = path !== '/' || (user !== null && !isLoading);

  return (
    <div className="flex h-screen bg-white">
      {showSidebar && (
        <Sidebar
          onSessionSelect={(sid) => onSessionSelect(sid)}
          currentSessionId={currentSessionId}
        />
      )}
      <div className="flex flex-col min-w-0" style={{ flex: '4 1 85%' }}>
        <div className="sticky top-0 z-30 bg-white border-b border-gray-200">
          <Header />
        </div>
        <div className="flex-1 min-h-0 relative">{children}</div>
      </div>
    </div>
  );
}

