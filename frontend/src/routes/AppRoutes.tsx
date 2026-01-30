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
 * - "/"      -> Chat đơn giản (không sidebar, không history) cho khách. Đã đăng nhập thì redirect /chat.
 * - "/chat"  -> Chat đầy đủ (sidebar, history) khi đã đăng nhập. Chưa đăng nhập thì redirect /.
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

  // Chưa đăng nhập vào "/chat" -> chuyển "/" (chat đơn giản)
  useEffect(() => {
    if (!isLoading && path === '/chat' && !user) {
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

  if (path === '/') return <Home />;
  if (path === '/login') return <Login />;
  if (path === '/signup') return <SignUp />;
  if (path === '/chat') return <Chat sessionId={sessionId} onSessionIdChange={onSessionIdChange} />;
  if (path === '/account') return <Account />;
  return <NotFound />;
}

