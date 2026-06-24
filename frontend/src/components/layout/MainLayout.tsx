import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useIsMobile } from '../../hooks/useIsMobile';
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
  const isMobile = useIsMobile();
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    // Navigation (sidebar links call navigate() → dispatches popstate) also
    // closes the mobile drawer so the user lands on the new view, not the menu.
    const onPopState = () => {
      setPath(window.location.pathname);
      setDrawerOpen(false);
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  // Returning to desktop width should never leave a stale open drawer behind.
  useEffect(() => {
    if (!isMobile) setDrawerOpen(false);
  }, [isMobile]);

  // Admins and viewers have their OWN full-screen app — no chat chrome (sidebar/header).
  const hideChrome = !!user?.is_admin || user?.role === 'viewer';
  // Sidebar + header chỉ khi đã đăng nhập — khách chỉ thấy trang Login, không chat/header cũ.
  const showSidebar = !hideChrome && (path.startsWith('/chat') || path.startsWith('/dashboard')) && user !== null && !isLoading;
  const showHeader = user !== null && !hideChrome;

  const sidebar = (
    <Sidebar
      onSessionSelect={(sid) => onSessionSelect(sid)}
      currentSessionId={currentSessionId}
      onRequestCloseDrawer={() => setDrawerOpen(false)}
    />
  );

  return (
    <div className="app" style={{ color: 'var(--text)' }}>
      {/* Desktop: sidebar is a fixed column. */}
      {showSidebar && !isMobile && sidebar}

      {/* Mobile: sidebar becomes a slide-in drawer over the content. */}
      {showSidebar && isMobile && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 60, pointerEvents: drawerOpen ? 'auto' : 'none' }}>
          <div
            onClick={() => setDrawerOpen(false)}
            style={{ position: 'absolute', inset: 0, background: 'oklch(0.2 0.02 70 / .4)', opacity: drawerOpen ? 1 : 0, transition: 'opacity .25s' }}
          />
          <div
            style={{
              position: 'absolute', top: 0, bottom: 0, left: 0, maxWidth: '86%',
              transform: drawerOpen ? 'translateX(0)' : 'translateX(-100%)',
              transition: 'transform .28s cubic-bezier(.4,0,.2,1)',
              boxShadow: '0 0 40px -8px oklch(0.2 0.02 70 / .4)',
            }}
          >
            {sidebar}
          </div>
        </div>
      )}

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {showHeader && (
          <Header onMenuClick={showSidebar && isMobile ? () => setDrawerOpen(true) : undefined} />
        )}

        <div style={{ flex: 1, minHeight: 0, position: 'relative', display: 'flex', flexDirection: 'column' }}>
          {children}
        </div>
      </div>
    </div>
  );
}

