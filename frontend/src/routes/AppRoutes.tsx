import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import Account from '../pages/Account';
import Chat from '../pages/Chat';
import Home from '../pages/Home';
import Login from '../pages/Login';
import SignUp from '../pages/SignUp';
import NotFound from '../pages/NotFound';

type AppRoutesProps = {
  sessionId: string | null;
  onSessionIdChange: (sessionId: string | null) => void;
};

/**
 * Routing patterns:
 * - "/"      -> Chat đơn giản (không sidebar, không history) cho khách. Đã đăng nhập thì redirect /chat.
 * - "/chat"  -> Chat mới (không có session)
 * - "/chat/:sessionId" -> Unassigned session (ngoài project)
 * - "/chat/:projectId" -> Project view (không có session)
 * - "/chat/:projectId/:sessionId" -> Project session
 * - "/account" -> Account
 */
export default function AppRoutes({ sessionId, onSessionIdChange }: AppRoutesProps) {
  const [path, setPath] = useState<string>(() => window.location.pathname);
  const { user, isLoading } = useAuth();

  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  // Đã đăng nhập vào "/" -> chuyển /chat
  useEffect(() => {
    if (!isLoading && path === '/' && user) {
      window.history.pushState({}, '', '/chat');
      window.dispatchEvent(new PopStateEvent('popstate'));
    }
  }, [path, user, isLoading]);

  // Chưa đăng nhập vào "/chat*" -> chuyển "/" (chat đơn giản)
  useEffect(() => {
    if (!isLoading && path.startsWith('/chat') && !user) {
      window.history.pushState({}, '', '/');
      window.dispatchEvent(new PopStateEvent('popstate'));
    }
  }, [path, user, isLoading]);

  // Đã đăng nhập vào "/login" hoặc "/signup" -> chuyển /chat
  useEffect(() => {
    if (!isLoading && (path === '/login' || path === '/signup') && user) {
      window.history.pushState({}, '', '/chat');
      window.dispatchEvent(new PopStateEvent('popstate'));
    }
  }, [path, user, isLoading]);

  // Parse chat route: /chat, /chat/:sessionId, /chat/:projectId, /chat/:projectId/:sessionId
  const parseChatRoute = (path: string): { projectId: string | null; sessionId: string | null } => {
    if (path === '/chat') {
      return { projectId: null, sessionId: null };
    }
    const parts = path.split('/').filter(Boolean); // ['chat', 'id1'] or ['chat', 'id1', 'id2']
    if (parts.length === 2 && parts[0] === 'chat') {
      // /chat/:id - could be sessionId (unassigned) or projectId
      // We'll determine this based on whether it's a UUID (project) or short ID (session)
      const id = parts[1];
      // Try to determine: if it looks like a UUID (has dashes), it's likely a projectId
      // Otherwise, treat as sessionId
      if (id.includes('-') && id.length > 20) {
        return { projectId: id, sessionId: null };
      }
      return { projectId: null, sessionId: id };
    }
    if (parts.length === 3 && parts[0] === 'chat') {
      // /chat/:projectId/:sessionId
      return { projectId: parts[1], sessionId: parts[2] };
    }
    return { projectId: null, sessionId: null };
  };

  if (path === '/') return <Home />;
  if (path === '/login') return <Login />;
  if (path === '/signup') return <SignUp />;
  if (path.startsWith('/chat')) {
    const { projectId, sessionId } = parseChatRoute(path);
    return <Chat projectId={projectId} sessionId={sessionId} onSessionIdChange={onSessionIdChange} />;
  }
  if (path === '/account') return <Account />;
  return <NotFound />;
}

