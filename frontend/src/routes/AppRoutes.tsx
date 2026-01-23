import { useEffect, useState } from 'react';
import Account from '../pages/Account';
import Chat from '../pages/Chat';
import Home from '../pages/Home';
import NotFound from '../pages/NotFound';

type AppRoutesProps = {
  sessionId: string | null;
  onSessionIdChange: (sessionId: string | null) => void;
};

/**
 * Minimal routing (no external router dependency).
 *
 * Supported paths:
 * - "/"      -> Home
 * - "/chat"  -> Chat
 * - "/account" -> Account
 * - other    -> NotFound
 *
 * Note: for production hosting (non-Vite), you may need SPA fallback configuration
 * so deep links like "/chat" still serve index.html.
 */
export default function AppRoutes({ sessionId, onSessionIdChange }: AppRoutesProps) {
  const [path, setPath] = useState<string>(() => window.location.pathname);

  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  if (path === '/') return <Home />;
  if (path === '/chat') return <Chat sessionId={sessionId} onSessionIdChange={onSessionIdChange} />;
  if (path === '/account') return <Account />;
  return <NotFound />;
}

