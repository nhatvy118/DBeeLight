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

  // Sidebar + header chỉ khi đã đăng nhập — khách chỉ thấy trang Login, không chat/header cũ.
  const showSidebar = path.startsWith('/chat') && user !== null && !isLoading;
  const showHeader = user !== null;

  return (
    <div className="app" style={{ color: 'var(--text)' }}>
      {showSidebar && (
        <Sidebar
          onSessionSelect={(sid) => onSessionSelect(sid)}
          currentSessionId={currentSessionId}
        />
      )}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {showHeader && <Header />}

        <div style={{ flex: 1, minHeight: 0, position: 'relative', display: 'flex', flexDirection: 'column' }}>
          {children}
        </div>
      </div>
    </div>
  );
}

