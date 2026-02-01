import { useEffect, useRef, useState } from 'react';
import { useAuth } from '../../context/AuthContext';
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
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [avatarMenuOpen, setAvatarMenuOpen] = useState(false);
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

  // Load selected project from localStorage
  // Show project whenever it's selected (even if it has no sessions yet)
  const loadSelectedProject = () => {
    const selectedProjectId = localStorage.getItem('selectedProjectId');
    if (selectedProjectId) {
      const projects = JSON.parse(localStorage.getItem('projects') || '[]');
      const project = projects.find((p: Project) => p.id === selectedProjectId);
      if (project) {
        setSelectedProject(project);
      } else {
        setSelectedProject(null);
      }
    } else {
      setSelectedProject(null);
    }
  };

  useEffect(() => {
    loadSelectedProject();

    // Listen for project selection changes
    const handleProjectSelected = () => {
      loadSelectedProject();
    };

    window.addEventListener('projectSelected', handleProjectSelected);

    // Also poll localStorage periodically to catch changes
    const interval = setInterval(() => {
      loadSelectedProject();
    }, 500);

    return () => {
      window.removeEventListener('projectSelected', handleProjectSelected);
      clearInterval(interval);
    };
  }, []);

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
      localStorage.removeItem('projects');
      localStorage.removeItem('selectedProjectId');
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
              className="hover:opacity-80 transition-opacity"
            >
              <img src={shareIcon} alt="Share" className="h-10" />
            </button>

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
                  className="absolute right-0 top-full mt-2 w-72 rounded-xl border border-gray-200 bg-white shadow-lg py-2 z-50"
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
                    className="flex items-center gap-3 px-4 py-2.5 text-gray-700 hover:bg-gray-50 transition-colors"
                    role="menuitem"
                  >
                    <img src={settingsIcon} alt="" className="w-5 h-5 text-gray-500" />
                    <span>Setting</span>
                  </a>
                  {/* Log out */}
                  <button
                    type="button"
                    onClick={() => {
                      setAvatarMenuOpen(false);
                      void handleLogout();
                    }}
                    className="flex w-full items-center gap-3 px-4 py-2.5 text-gray-700 hover:bg-gray-50 transition-colors text-left"
                    role="menuitem"
                  >
                    <img src={logoutIcon} alt="" className="w-5 h-5 text-gray-500" />
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
    </div>
  );
}

