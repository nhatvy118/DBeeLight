import { useEffect, useState } from 'react';
import settingsIcon from '../../assets/icons/Settings.svg';
import userIcon from '../../assets/icons/User.svg';
import chevronDownIcon from '../../assets/icons/ChevronDown.svg';
import shareIcon from '../../assets/icons/Share.svg';

type AuthUser = {
  name?: string;
  email?: string;
  picture?: string;
};

export default function Header() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    const loadMe = async () => {
      try {
        setIsLoading(true);
        const res = await fetch('/api/auth/me', { method: 'GET', credentials: 'include' });
        const data = (await res.json()) as { authenticated: boolean; user?: AuthUser | null };
        setUser(data.authenticated ? (data.user ?? null) : null);
      } catch {
        setUser(null);
      } finally {
        setIsLoading(false);
      }
    };
    void loadMe();
  }, []);

  const handleLogin = () => {
    // Backend will redirect to Google, then back to frontend.
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

  return (
    <div className="w-full flex justify-between items-center px-6 py-4">
      {/* Logo Section - Only show on home page when not logged in */}
      {isHomePage && !user && (
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 flex items-center justify-center bg-gray-900 rounded text-white font-bold text-lg">
            2
          </div>
          <span className="text-xl font-semibold text-gray-900">LightDBee</span>
          <button className="text-gray-600 hover:text-gray-900 transition-colors">
            <img src={chevronDownIcon} alt="Dropdown" className="w-5 h-5" />
          </button>
        </div>
      )}

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

            {/* Settings Icon */}
            <button className="w-8 h-8 rounded-full hover:bg-gray-100 flex items-center justify-center transition-colors">
              <img src={settingsIcon} alt="Settings" className="w-8 h-8" />
            </button>

            {/* Profile Icon */}
            <button className="w-8 h-8 rounded-full hover:bg-gray-100 flex items-center justify-center transition-colors">
              {user.picture ? (
                <img
                  src={user.picture}
                  alt={user.name || user.email || 'User'}
                  className="w-8 h-8 rounded-full"
                  referrerPolicy="no-referrer"
                />
              ) : (
                <img src={userIcon} alt="User" className="w-5 h-5" />
              )}
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              disabled={isLoading}
              onClick={handleLogin}
              className="px-4 py-2 bg-black text-white rounded-lg hover:bg-gray-800 transition-colors disabled:opacity-60 disabled:cursor-not-allowed font-medium text-sm"
            >
              Log in
            </button>
            <button
              type="button"
              disabled={isLoading}
              onClick={handleSignUp}
              className="px-4 py-2 bg-white border-2 border-gray-300 text-gray-900 rounded-lg hover:bg-gray-50 hover:border-gray-400 transition-colors disabled:opacity-60 disabled:cursor-not-allowed font-medium text-sm"
            >
              Sign up
            </button>
            <button className="w-8 h-8 rounded-full bg-gray-100 hover:bg-gray-200 flex items-center justify-center transition-colors">
              <img src={userIcon} alt="User" className="w-5 h-5" />
            </button>
          </>
        )}
      </div>
    </div>
  );
}

