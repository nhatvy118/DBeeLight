import { useEffect, useLayoutEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import Account from '../pages/Account';
import AdminDashboard from '../pages/AdminDashboard';
import Chat from '../pages/Chat';
import Dashboard from '../pages/Dashboard';
import Login from '../pages/Login';
import NotFound from '../pages/NotFound';

type AppRoutesProps = {
  sessionId: string | null;
  onSessionIdChange: (sessionId: string | null) => void;
};

/**
 * Routing patterns:
 * - "/"      -> Redirect /login (chưa đăng nhập) hoặc /chat (đã đăng nhập)
 * - "/chat"  -> Chat mới (không có session, bắt buộc đăng nhập)
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

  // Land on / → /login immediately (matches dev UX).
  useEffect(() => {
    if (window.location.pathname === '/') {
      window.history.replaceState({}, '', '/login');
      setPath('/login');
    }
  }, []);

  // Chưa đăng nhập: đưa về /login ngay (replaceState, không để URL /chat).
  useLayoutEffect(() => {
    if (isLoading || user) return;
    const pathname = window.location.pathname;
    const isPublic = pathname === '/' || pathname === '/login';
    if (!isPublic) {
      window.history.replaceState({}, '', '/login');
      setPath('/login');
    }
  }, [path, user, isLoading]);

  // Đã đăng nhập vào "/" hoặc "/login" -> chuyển /chat
  useEffect(() => {
    if (!isLoading && user && (path === '/' || path === '/login')) {
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

  const pathname = window.location.pathname;

  // Public routes — render regardless of auth state.
  if (path === '/login' || pathname === '/login') return <Login />;

  // Auth gate for everything below. On marketing/login paths, keep showing
  // <Login> while /api/auth/me loads so production (/) never looks blank if
  // the API is slow or down. On /chat* we still render nothing to avoid a
  // flash of the empty chat shell for logged-out users.
  if (isLoading) {
    const isMarketingPath = path === '/' || path === '/login';
    if (isMarketingPath) return <Login />;
    return null;
  }
  if (!user) {
    // Đồng bộ URL trước khi paint (phòng deploy cũ / race sau logout).
    if (pathname !== '/login') {
      window.history.replaceState({}, '', '/login');
    }
    return <Login />;
  }

  if (path.startsWith('/dashboard/')) {
    const pid = path.slice('/dashboard/'.length).split('/').filter(Boolean)[0];
    if (pid) return <Dashboard projectId={pid} />;
  }
  if (path.startsWith('/chat')) {
    const { projectId, sessionId } = parseChatRoute(path);
    return <Chat projectId={projectId} sessionId={sessionId} onSessionIdChange={onSessionIdChange} />;
  }
  if (path === '/account') return <Account />;
  // Admin-only dashboard. Non-admins fall through to NotFound (no leak of the page).
  if (path === '/admin') return user.is_admin ? <AdminDashboard /> : <NotFound />;
  return <NotFound />;
}

