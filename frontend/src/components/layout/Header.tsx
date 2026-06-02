import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useAuth } from '../../context/AuthContext';
import { url } from '../../services/api';
import { useTheme } from '../../context/ThemeContext';
import ShareSessionModal from '../modals/ShareSessionModal';
import StorageModal from '../modals/StorageModal';
import { Icons, BeeBadge } from '../../icons';

type Project = {
  id: string;
  name: string;
  createdAt: string;
};

export default function Header() {
  const { user } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [avatarMenuOpen, setAvatarMenuOpen] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareSessionId, setShareSessionId] = useState<string | null>(null);
  const [storageModalOpen, setStorageModalOpen] = useState(false);
  const avatarMenuRef = useRef<HTMLDivElement>(null);

  // Close avatar menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (avatarMenuRef.current && !avatarMenuRef.current.contains(e.target as Node)) {
        setAvatarMenuOpen(false);
      }
    };
    if (avatarMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [avatarMenuOpen]);

  // Load selected project from URL - URL is source of truth
  useEffect(() => {
    const updateProjectFromURL = () => {
      const path = window.location.pathname;
      // Parse URL: /chat/:projectId or /chat/:projectId/:sessionId
      const parts = path.split('/').filter(Boolean);
      if (parts.length >= 2 && parts[0] === 'chat') {
        const projectId = parts[1];
        // Check if it's a project ID (UUID format) or session ID (short format)
        if (projectId.includes('-') && projectId.length > 20) {
          // Likely a project ID (UUID)
          let projects: Project[] = [];
          try {
            projects = JSON.parse(localStorage.getItem('projects') || '[]') as Project[];
          } catch {
            projects = [];
          }
          const project = projects.find((p: Project) => p.id === projectId);
          if (project) {
            setSelectedProject(project);
            return;
          }
        }
      }
      // No project in URL
      setSelectedProject(null);
    };

    updateProjectFromURL();

    // Listen for URL changes
    const handlePopState = () => {
      updateProjectFromURL();
    };

    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener('popstate', handlePopState);
    };
  }, []);

  // Open share modal — requires being inside a specific session.
  // Walk the URL to figure out which session is currently open. Used by
  // the Share + Export buttons (both need a session_id to act on).
  const currentSessionFromUrl = (): string | null => {
    const parts = window.location.pathname.split('/').filter(Boolean);
    if (parts.length >= 2 && parts[0] === 'chat') {
      if (parts.length === 3) return parts[2];
      if (parts.length === 2) {
        const id = parts[1];
        if (!(id.includes('-') && id.length > 20)) return id;
      }
    }
    return null;
  };

  const handleShareClick = () => {
    const sessionId = currentSessionFromUrl();
    if (!sessionId) {
      window.alert('Open a chat session before sharing.');
      return;
    }
    setShareSessionId(sessionId);
    setShareModalOpen(true);
  };

  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!exportMenuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node)) {
        setExportMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [exportMenuOpen]);

  const handleExportMarkdown = async () => {
    const sessionId = currentSessionFromUrl();
    if (!sessionId) {
      window.alert('Open a chat session before exporting.');
      return;
    }
    setExportMenuOpen(false);
    try {
      const { downloadSessionMarkdown } = await import('../../services/api');
      await downloadSessionMarkdown(sessionId);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Failed to export');
    }
  };

  const handleExportPdf = () => {
    const sessionId = currentSessionFromUrl();
    if (!sessionId) {
      window.alert('Open a chat session before exporting.');
      return;
    }
    setExportMenuOpen(false);
    // Open the print-preview route in a new tab — auto-triggers the
    // browser print dialog where the user picks "Save as PDF".
    const projectIdFromUrl = (() => {
      const parts = window.location.pathname.split('/').filter(Boolean);
      if (parts.length === 3 && parts[0] === 'chat') return parts[1];
      return null;
    })();
    const target = projectIdFromUrl
      ? `/chat/${projectIdFromUrl}/${sessionId}/print`
      : `/chat/${sessionId}/print`;
    window.open(target, '_blank', 'noopener');
  };

  const handleLogout = async () => {
    try {
      await fetch(url('/api/auth/logout'), { method: 'POST', credentials: 'include' });
    } catch {
      // still leave the app — cookie may already be cleared
    }
    try {
      localStorage.removeItem('projects');
      localStorage.removeItem('lastSessionId');
      localStorage.removeItem('lastSessionIdForProject');
    } catch {
      // ignore if storage is blocked
    }
    // Full navigation to /login — avoid setUser(null) first (prevents a flash of
    // guest chat UI on /chat before redirect, especially on production builds).
    window.location.replace('/login');
  };

  // Read pathname from the URL on every render — AppRoutes uses replaceState/pushState
  // without always firing popstate, so a cached path state can stay on "/" while the
  // real URL is already "/login" and wrongly show the header "Log in" button.
  const [, setNavTick] = useState(0);
  useEffect(() => {
    const onNav = () => setNavTick((n) => n + 1);
    window.addEventListener('popstate', onNav);
    return () => window.removeEventListener('popstate', onNav);
  }, []);

  const userInitial = (user?.name || user?.email || '?').slice(0, 1).toUpperCase();
  const hasSession = currentSessionFromUrl() !== null;

  const menuItem = (icon: ReactNode, label: string, onClick: () => void, danger = false) => (
    <button
      type="button"
      onClick={onClick}
      role="menuitem"
      className="focusable"
      style={{
        width: '100%', display: 'flex', alignItems: 'center', gap: 11, padding: '10px 12px',
        borderRadius: 'var(--r-sm)', textAlign: 'left', fontSize: 14, fontWeight: 600,
        color: danger ? 'oklch(0.58 0.19 25)' : 'var(--text-soft)', background: 'transparent',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = danger ? 'oklch(0.95 0.05 25)' : 'var(--surface-2)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
    >
      {icon}
      {label}
    </button>
  );

  return (
    <header
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 24px', borderBottom: '1px solid var(--border)', flexShrink: 0, background: 'var(--bg)',
      }}
    >
      {/* Left Section - Logo or Project */}
      <div style={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
        {selectedProject ? (
          <>
            <span style={{ width: 30, height: 30, borderRadius: 9, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)', flexShrink: 0 }}>
              <Icons.Folder size={17} />
            </span>
            <span style={{ fontSize: 15.5, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {selectedProject.name}
            </span>
          </>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <BeeBadge size={30} />
            <span style={{ fontSize: 17, fontWeight: 800, letterSpacing: '-.02em' }}>LightDBee</span>
          </div>
        )}
      </div>

      {/* Right Section */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 'auto' }}>
        {user ? (
          <>
            {/* Share */}
            <button
              type="button"
              onClick={handleShareClick}
              className="btn btn-outline"
              style={{ padding: '8px 16px', fontSize: 13.5, opacity: hasSession ? 1 : 0.55 }}
              title="Share this chat"
            >
              <Icons.Share size={16} />
              Share
            </button>

            {/* Export + dropdown */}
            <div style={{ position: 'relative' }} ref={exportMenuRef}>
              <button
                type="button"
                onClick={() => setExportMenuOpen((o) => !o)}
                className="btn btn-ghost"
                style={{ fontSize: 13.5 }}
                title="Export this chat"
                aria-haspopup="true"
                aria-expanded={exportMenuOpen}
              >
                <Icons.Export size={16} />
                Export
              </button>
              {exportMenuOpen && (
                <div
                  className="card pop-shadow scale-in"
                  style={{ position: 'absolute', right: 0, top: 'calc(100% + 8px)', width: 232, borderRadius: 'var(--r)', padding: 7, zIndex: 50, transformOrigin: 'top right' }}
                  role="menu"
                >
                  {menuItem(<Icons.Download size={18} />, 'Download Markdown', handleExportMarkdown)}
                  {menuItem(<Icons.Export size={18} />, 'Save as PDF', handleExportPdf)}
                </div>
              )}
            </div>

            {/* Theme toggle */}
            <button
              onClick={toggleTheme}
              title="Toggle theme"
              className="focusable"
              style={{ width: 38, height: 38, borderRadius: 10, display: 'grid', placeItems: 'center', color: 'var(--text-soft)', border: '1px solid var(--border)', background: 'transparent' }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
            >
              {theme === 'dark' ? <Icons.Sun size={18} /> : <Icons.Moon size={18} />}
            </button>

            {/* Avatar + dropdown menu */}
            <div style={{ position: 'relative' }} ref={avatarMenuRef}>
              <button
                type="button"
                onClick={() => setAvatarMenuOpen((o) => !o)}
                className="focusable"
                style={{ width: 38, height: 38, borderRadius: 99, display: 'grid', placeItems: 'center', overflow: 'hidden', background: 'linear-gradient(145deg, var(--accent), var(--accent-strong))', color: 'var(--on-accent)', fontWeight: 800, fontSize: 15 }}
                aria-expanded={avatarMenuOpen}
                aria-haspopup="true"
              >
                {user.picture ? (
                  <img src={user.picture} alt={user.name || user.email || 'User'} style={{ width: 38, height: 38, borderRadius: 99, objectFit: 'cover' }} referrerPolicy="no-referrer" />
                ) : (
                  userInitial
                )}
              </button>

              {avatarMenuOpen && (
                <div
                  className="card pop-shadow scale-in"
                  style={{ position: 'absolute', right: 0, top: 'calc(100% + 8px)', width: 264, borderRadius: 'var(--r)', padding: 8, zIndex: 50, transformOrigin: 'top right' }}
                  role="menu"
                >
                  {/* User info */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '8px 10px 12px', borderBottom: '1px solid var(--border)', marginBottom: 6 }}>
                    {user.picture ? (
                      <img src={user.picture} alt="" style={{ width: 38, height: 38, borderRadius: 99, objectFit: 'cover', flexShrink: 0 }} referrerPolicy="no-referrer" />
                    ) : (
                      <div style={{ width: 38, height: 38, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'linear-gradient(145deg, var(--accent), var(--accent-strong))', color: 'var(--on-accent)', fontWeight: 800, fontSize: 16 }}>
                        {userInitial}
                      </div>
                    )}
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.name || '—'}</div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.email || '—'}</div>
                    </div>
                  </div>
                  {menuItem(<Icons.Settings size={18} />, 'Account settings', () => { setAvatarMenuOpen(false); window.history.pushState({}, '', '/account'); window.dispatchEvent(new PopStateEvent('popstate')); })}
                  {menuItem(theme === 'dark' ? <Icons.Sun size={18} /> : <Icons.Moon size={18} />, theme === 'dark' ? 'Light mode' : 'Dark mode', toggleTheme)}
                  {menuItem(<Icons.HardDrive size={18} />, 'Storage', () => { setAvatarMenuOpen(false); setStorageModalOpen(true); })}
                  <div style={{ height: 1, background: 'var(--border)', margin: '6px 4px' }} />
                  {menuItem(<Icons.Logout size={18} />, 'Log out', () => { setAvatarMenuOpen(false); void handleLogout(); }, true)}
                </div>
              )}
            </div>
          </>
        ) : null}
      </div>

      {/* Share Modal */}
      {shareModalOpen && shareSessionId && (
        <ShareSessionModal
          sessionId={shareSessionId}
          open={shareModalOpen}
          onClose={() => setShareModalOpen(false)}
        />
      )}
      <StorageModal open={storageModalOpen} onClose={() => setStorageModalOpen(false)} />
    </header>
  );
}

