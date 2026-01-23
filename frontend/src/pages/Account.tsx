import { useEffect, useState } from 'react';

type AuthUser = {
  name?: string;
  email?: string;
  picture?: string;
  email_verified?: boolean;
  given_name?: string;
  family_name?: string;
  locale?: string;
  hd?: string;
  sub?: string;
};

export default function Account() {
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [displayName, setDisplayName] = useState<string>('');
  const [username, setUsername] = useState<string>('');
  const [initialDisplayName, setInitialDisplayName] = useState<string>('');
  const [initialUsername, setInitialUsername] = useState<string>('');

  const storageKey = user?.sub ? `profile_overrides_${user.sub}` : null;

  useEffect(() => {
    const load = async () => {
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
    void load();
  }, []);

  // Initialize form values (and local overrides) once user is loaded
  useEffect(() => {
    if (!user) return;
    const email = user.email ?? '';
    const defaultUsername = email.includes('@') ? email.split('@')[0] : '';
    const defaultDisplayName = user.name ?? user.given_name ?? defaultUsername ?? '';

    let overrides: { displayName?: string; username?: string } | null = null;
    if (storageKey) {
      try {
        overrides = JSON.parse(localStorage.getItem(storageKey) || 'null') as any;
      } catch {
        overrides = null;
      }
    }

    const nextDisplayName = (overrides?.displayName || defaultDisplayName).trim();
    const nextUsername = (overrides?.username || defaultUsername).trim();
    setDisplayName(nextDisplayName);
    setUsername(nextUsername);
    setInitialDisplayName(nextDisplayName);
    setInitialUsername(nextUsername);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.sub]);

  const isDirty = displayName !== initialDisplayName || username !== initialUsername;

  const handleCancel = () => {
    setDisplayName(initialDisplayName);
    setUsername(initialUsername);
  };

  const handleSave = () => {
    if (!storageKey) return;
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        displayName: displayName.trim(),
        username: username.trim(),
      }),
    );
    setInitialDisplayName(displayName.trim());
    setInitialUsername(username.trim());
  };

  return (
    <div className="h-full overflow-y-auto px-6 py-8 bg-white">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-gray-900">Edit profile</h1>
          <a className="text-sm text-blue-600 hover:text-blue-700 underline" href="/chat">
            Back to Chat
          </a>
        </div>

        <div className="mt-6 rounded-3xl border border-gray-200 bg-white shadow-sm p-6">
          {isLoading ? (
            <div className="text-sm text-gray-600">Loading…</div>
          ) : !user ? (
            <div className="text-sm text-gray-600">
              You are not signed in. Use <span className="font-medium">Sign in with Google</span> in the header.
            </div>
          ) : (
            <>
              {/* Avatar */}
              <div className="flex justify-center py-4">
                <div className="relative">
                  {user.picture ? (
                    <img
                      src={user.picture}
                      alt={user.name || user.email || 'User'}
                      className="w-40 h-40 rounded-full object-cover border border-gray-200"
                      referrerPolicy="no-referrer"
                    />
                  ) : (
                    <div className="w-40 h-40 rounded-full bg-slate-600 flex items-center justify-center text-white text-5xl font-semibold">
                      {(user.name || user.email || '?').slice(0, 1).toUpperCase()}
                    </div>
                  )}

                  {/* Camera button (placeholder) */}
                  <button
                    type="button"
                    className="absolute bottom-2 right-2 w-10 h-10 rounded-full bg-white border border-gray-300 shadow-sm flex items-center justify-center hover:bg-gray-50 transition-colors"
                    title="Change avatar (not supported)"
                    onClick={() => window.alert("Avatar update isn't supported (Google profile is managed by Google).")}
                  >
                    <svg className="w-5 h-5 text-gray-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M3 7h3l2-3h8l2 3h3v13H3V7z"
                      />
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M12 17a4 4 0 100-8 4 4 0 000 8z"
                      />
                    </svg>
                  </button>
                </div>
              </div>

              {/* Form */}
              <div className="mt-4 space-y-4">
                <div className="rounded-2xl border border-gray-200 px-4 py-3">
                  <label className="block text-xs font-medium text-gray-500">Display name</label>
                  <input
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    className="mt-1 w-full text-base text-gray-900 outline-none bg-transparent"
                    placeholder="Your name"
                  />
                </div>

                <div className="rounded-2xl border border-gray-200 px-4 py-3">
                  <label className="block text-xs font-medium text-gray-500">Username</label>
                  <input
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="mt-1 w-full text-base text-gray-900 outline-none bg-transparent"
                    placeholder="username"
                  />
                </div>
                <div className="mt-6 flex items-center justify-end gap-3">
                  <button
                    type="button"
                    onClick={handleCancel}
                    disabled={!isDirty}
                    className="px-6 py-2 rounded-full bg-gray-100 hover:bg-gray-200 text-sm font-medium text-gray-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={!isDirty}
                    className="px-6 py-2 rounded-full bg-black text-white text-sm font-medium hover:bg-gray-900 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Save
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

