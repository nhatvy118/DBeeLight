import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import AcceptShare from '../pages/AcceptShare';
import Account from '../pages/Account';
import Chat from '../pages/Chat';
import Login from '../pages/Login';
import PrintChat from '../pages/PrintChat';
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

  // Chưa đăng nhập vào bất kỳ trang nào (trừ /login, /signup, /share) -> chuyển /login
  useEffect(() => {
    if (isLoading) return;
    if (user) return;
    const isPublic =
      path === '/login' ||
      path.startsWith('/share/');
    if (!isPublic) {
      window.history.pushState({}, '', '/login');
      window.dispatchEvent(new PopStateEvent('popstate'));
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

  // Public routes — render regardless of auth state.
  if (path === '/login') return <Login />;
  if (path.startsWith('/share/accept/')) {
    const token = path.slice('/share/accept/'.length);
    return <AcceptShare token={decodeURIComponent(token)} />;
  }

  // Auth gate for everything below. While the /api/auth/me check is in flight
  // we render nothing — prevents a flash of the Chat empty state for users
  // who turn out to be logged out. Once the check resolves and there's no
  // user, fall through to <Login /> (the useEffect above also rewrites the URL).
  if (isLoading) return null;
  if (!user) return <Login />;

  // Print-friendly view of a chat session: ``/chat/.../print``. Used as the
  // PDF export path — the page auto-triggers ``window.print()`` and the user
  // saves to PDF via the browser dialog.
  if (path.startsWith('/chat/') && path.endsWith('/print')) {
    const inner = path.slice('/chat/'.length, -'/print'.length);
    const parts = inner.split('/').filter(Boolean);
    const sessionId = parts[parts.length - 1];
    if (sessionId) return <PrintChat sessionId={sessionId} />;
  }
  if (path.startsWith('/chat')) {
    const { projectId, sessionId } = parseChatRoute(path);
    return <Chat projectId={projectId} sessionId={sessionId} onSessionIdChange={onSessionIdChange} />;
  }
  if (path === '/account') return <Account />;
  return <NotFound />;
}

