import { useEffect, useRef, useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useTheme } from '../../context/ThemeContext';
import ShareSessionModal from '../modals/ShareSessionModal';
import settingsIcon from '../../assets/icons/Settings.svg';
import logoutIcon from '../../assets/icons/Logout.svg';
import userIcon from '../../assets/icons/User.svg';
import shareIcon from '../../assets/icons/Share.svg';
import folderIcon from '../../assets/icons/Folder.svg';
import beeLogo from '../../assets/icons/bee.png';

type Project = {
  id: string;
  name: string;
  createdAt: string;
};

export default function Header() {
  const { user, isLoading, setUser } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [avatarMenuOpen, setAvatarMenuOpen] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareSessionId, setShareSessionId] = useState<string | null>(null);
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

  const handleLogin = () => {
    const next = window.location.pathname === '/' ? '/chat' : window.location.pathname;
    window.location.href = `/api/auth/google/login?next=${encodeURIComponent(next)}`;
  };

  const handleSignUp = () => {
    // Same as login for Google OAuth
    handleLogin();
  };

  const handleLogout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
    } finally {
      setUser(null);
      try {
        localStorage.removeItem('projects');
        localStorage.removeItem('lastSessionId');
        localStorage.removeItem('lastSessionIdForProject');
      } catch {
        // ignore if storage is blocked
      }
      window.history.pushState({}, '', '/');
      window.dispatchEvent(new PopStateEvent('popstate'));
    }
  };

  // Check if we're on the home page
  const [path, setPath] = useState<string>(() => window.location.pathname);

  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const isHomePage = path === '/';
  const isLoginPage = path === '/login';
  const isSignUpPage = path === '/signup';
  const showLogo = (isHomePage || isLoginPage || isSignUpPage) && !user;

  return (
    <div className="w-full flex justify-between items-center px-6 py-4">
      {/* Left Section - Logo or Project */}
      <div className="flex items-center gap-2">
        {showLogo ? (
          <div className="flex items-center gap-2">
            <img src={beeLogo} alt="" className="h-8 w-auto object-contain" />
            <span className="text-xl font-semibold text-gray-900 tracking-tight">LightDBee</span>
          </div>
        ) : selectedProject ? (
          <div className="flex items-center gap-3">
            <img src={folderIcon} alt="Folder" className="w-7 h-7" />
            <span className="text-xl font-semibold text-gray-900">{selectedProject.name}</span>
          </div>
        ) : null}
      </div>

      {/* Right Section */}
      <div className="flex items-center gap-3 ml-auto">
        {user ? (
          <>
            {/* Share Button */}
            <button
              type="button"
              onClick={handleShareClick}
              className="hover:opacity-80 transition-opacity"
              title="Share this chat"
            >
              <img src={shareIcon} alt="Share" className="h-10" />
            </button>

            {/* Export Button + dropdown */}
            <div className="relative" ref={exportMenuRef}>
              <button
                type="button"
                onClick={() => setExportMenuOpen((o) => !o)}
                className="px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                title="Export this chat"
                aria-haspopup="true"
                aria-expanded={exportMenuOpen}
              >
                Export
              </button>
              {exportMenuOpen && (
                <div
                  className="absolute right-0 top-full mt-2 w-56 rounded-xl border border-gray-200 bg-white shadow-lg dark:bg-slate-900 dark:border-slate-700 py-1 z-50"
                  role="menu"
                >
                  <button
                    type="button"
                    onClick={handleExportMarkdown}
                    className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                    role="menuitem"
                  >
                    Download Markdown (.md)
                  </button>
                  <button
                    type="button"
                    onClick={handleExportPdf}
                    className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                    role="menuitem"
                  >
                    Save as PDF (browser print)
                  </button>
                </div>
              )}
            </div>

            {/* Avatar + dropdown menu */}
            <div className="relative" ref={avatarMenuRef}>
              <button
                type="button"
                onClick={() => setAvatarMenuOpen((o) => !o)}
                className="w-8 h-8 rounded-full hover:bg-gray-100 flex items-center justify-center transition-colors overflow-hidden"
                aria-expanded={avatarMenuOpen}
                aria-haspopup="true"
              >
                {user.picture ? (
                  <img
                    src={user.picture}
                    alt={user.name || user.email || 'User'}
                    className="w-8 h-8 rounded-full object-cover"
                    referrerPolicy="no-referrer"
                  />
                ) : (
                  <div className="w-8 h-8 rounded-full bg-slate-500 flex items-center justify-center">
                    <span className="text-white text-sm font-medium">
                      {(user.name || user.email || '?').slice(0, 1).toUpperCase()}
                    </span>
                  </div>
                )}
              </button>

              {avatarMenuOpen && (
                <div
                  className="absolute right-0 top-full mt-2 w-72 rounded-xl border border-gray-200 bg-white shadow-lg dark:bg-slate-900 dark:border-slate-700 py-2 z-50"
                  role="menu"
                >
                  {/* User info */}
                  <div className="flex items-center gap-3 px-4 py-3">
                    {user.picture ? (
                      <img
                        src={user.picture}
                        alt=""
                        className="w-10 h-10 rounded-full object-cover flex-shrink-0"
                        referrerPolicy="no-referrer"
                      />
                    ) : (
                      <div className="w-10 h-10 rounded-full bg-slate-500 flex items-center justify-center flex-shrink-0 text-white font-medium">
                        {(user.name || user.email || '?').slice(0, 1).toUpperCase()}
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-gray-900 font-semibold truncate">
                        {user.name || '—'}
                      </p>
                      <p className="text-gray-500 text-sm truncate">
                        {user.email || '—'}
                      </p>
                    </div>
                  </div>
                  <div className="border-t border-gray-100 my-1" />
                  {/* Setting */}
                  <a
                    href="/account"
                    onClick={() => setAvatarMenuOpen(false)}
                    className="flex items-center gap-3 px-4 py-2.5 text-gray-700 hover:bg-gray-50 transition-colors dark:text-gray-200 dark:hover:bg-slate-800"
                    role="menuitem"
                  >
                    <img src={settingsIcon} alt="" className="w-5 h-5 text-gray-500 dark:invert dark:opacity-80" />
                    <span>Setting</span>
                  </a>
                  {/* Theme toggle */}
                  <button
                    type="button"
                    onClick={toggleTheme}
                    className="flex w-full items-center gap-3 px-4 py-2.5 text-gray-700 hover:bg-gray-50 transition-colors text-left dark:text-gray-200 dark:hover:bg-slate-800"
                    role="menuitem"
                  >
                    {theme === 'dark' ? (
                      <svg className="w-5 h-5 text-gray-500 dark:text-gray-300" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="4" />
                        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
                      </svg>
                    ) : (
                      <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                      </svg>
                    )}
                    <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
                  </button>
                  {/* Log out */}
                  <button
                    type="button"
                    onClick={() => {
                      setAvatarMenuOpen(false);
                      void handleLogout();
                    }}
                    className="flex w-full items-center gap-3 px-4 py-2.5 text-gray-700 hover:bg-gray-50 transition-colors text-left dark:text-gray-200 dark:hover:bg-slate-800"
                    role="menuitem"
                  >
                    <img src={logoutIcon} alt="" className="w-5 h-5 text-gray-500 dark:invert dark:opacity-80" />
                    <span>Log out</span>
                  </button>
                </div>
              )}
            </div>
          </>
        ) : (
          <>
            {!isLoginPage && !isSignUpPage && (
              <>
                <button
                  type="button"
                  disabled={isLoading}
                  onClick={() => {
                    window.history.pushState({}, '', '/login');
                    window.dispatchEvent(new PopStateEvent('popstate'));
                  }}
                  className="px-4 py-2 bg-black text-white rounded-lg hover:bg-gray-800 transition-colors disabled:opacity-60 disabled:cursor-not-allowed font-medium text-sm"
                >
                  Log in
                </button>
                <button
                  type="button"
                  disabled={isLoading}
                  onClick={() => {
                    window.history.pushState({}, '', '/signup');
                    window.dispatchEvent(new PopStateEvent('popstate'));
                  }}
                  className="px-4 py-2 bg-white border-2 border-gray-300 text-gray-900 rounded-lg hover:bg-gray-50 hover:border-gray-400 transition-colors disabled:opacity-60 disabled:cursor-not-allowed font-medium text-sm"
                >
                  Sign up
                </button>
                <button className="w-8 h-8 rounded-full bg-gray-100 hover:bg-gray-200 flex items-center justify-center transition-colors">
                  <img src={userIcon} alt="User" className="w-5 h-5" />
                </button>
              </>
            )}
          </>
        )}
      </div>

      {/* Share Modal */}
      {shareModalOpen && shareSessionId && (
        <ShareSessionModal
          sessionId={shareSessionId}
          open={shareModalOpen}
          onClose={() => setShareModalOpen(false)}
        />
      )}
    </div>
  );
}

