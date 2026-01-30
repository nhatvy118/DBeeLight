import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useAuth } from '../../context/AuthContext';
import Header from './Header';
import Sidebar from './Sidebar';

type MainLayoutProps = {
  children: ReactNode;
  currentSessionId: string | null;
  onSessionSelect: (sessionId: string | null) => void;
};

export default function MainLayout({ children, currentSessionId, onSessionSelect }: MainLayoutProps) {
  const [path, setPath] = useState<string>(() => window.location.pathname);
  const { user, isLoading } = useAuth();

  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  // Sidebar: chỉ hiện khi đã đăng nhập và đang ở /chat (không hiện ở "/" - chat đơn giản cho khách)
  const showSidebar = path === '/chat' && user !== null && !isLoading;

  return (
    <div className="flex h-screen bg-white">
      {showSidebar && (
        <Sidebar
          onSessionSelect={(sid) => onSessionSelect(sid)}
          currentSessionId={currentSessionId}
        />
      )}
      <div className="flex flex-col min-w-0" style={{ flex: '4 1 85%' }}>
        <Header />

        <div className="flex-1 min-h-0 relative">{children}</div>
      </div>
    </div>
  );
}

