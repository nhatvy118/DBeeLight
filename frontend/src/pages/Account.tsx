import { useEffect, useState } from 'react';
import { url } from '../services/api';
import { useLanguage, LANGUAGE_OPTIONS } from '../context/LanguageContext';
import { Icons } from '../icons';

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
  const { language, setLanguage } = useLanguage();
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
        const res = await fetch(url('/api/auth/me'), { method: 'GET', credentials: 'include' });
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
    <div style={{ height: '100%', overflowY: 'auto', padding: '32px 24px', background: 'var(--bg)' }}>
      <div style={{ maxWidth: 640, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h1 style={{ fontSize: 24, fontWeight: 800, letterSpacing: '-.02em' }}>Account settings</h1>
          <a style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--accent-ink)', textDecoration: 'none' }} href="/chat">Back to chat</a>
        </div>

        <div className="card soft-shadow" style={{ marginTop: 24, borderRadius: 'var(--r-lg)', padding: 26 }}>
          {isLoading ? (
            <div style={{ fontSize: 14, color: 'var(--text-muted)' }}>Loading…</div>
          ) : !user ? (
            <div style={{ fontSize: 14, color: 'var(--text-muted)' }}>
              You are not signed in. Use <span style={{ fontWeight: 600 }}>Continue with Google</span> on the login page.
            </div>
          ) : (
            <>
              {/* Avatar */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, paddingBottom: 22, marginBottom: 22, borderBottom: '1px solid var(--border)' }}>
                {user.picture ? (
                  <img src={user.picture} alt={user.name || user.email || 'User'} style={{ width: 64, height: 64, borderRadius: 99, objectFit: 'cover' }} referrerPolicy="no-referrer" />
                ) : (
                  <div style={{ width: 64, height: 64, borderRadius: 99, display: 'grid', placeItems: 'center', background: 'linear-gradient(145deg, var(--accent), var(--accent-strong))', color: 'var(--on-accent)', fontWeight: 800, fontSize: 26 }}>
                    {(user.name || user.email || '?').slice(0, 1).toUpperCase()}
                  </div>
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 16, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.name || '—'}</div>
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.email || '—'}</div>
                  <p style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 6 }}>Your photo is managed by your Google account.</p>
                </div>
              </div>

              {/* Form */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div>
                  <label className="field-label">Display name</label>
                  <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="field focusable" placeholder="Your name" />
                </div>
                <div>
                  <label className="field-label">Username</label>
                  <input value={username} onChange={(e) => setUsername(e.target.value)} className="field focusable" placeholder="username" />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 10, marginTop: 10 }}>
                  <button type="button" onClick={handleCancel} disabled={!isDirty} className="btn btn-outline" style={{ padding: '11px 18px', opacity: isDirty ? 1 : 0.5 }}>Cancel</button>
                  <button type="button" onClick={handleSave} disabled={!isDirty} className="btn btn-primary" style={{ padding: '11px 22px', opacity: isDirty ? 1 : 0.5 }}>Save changes</button>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Preferences — answer language */}
        <div className="card soft-shadow" style={{ marginTop: 20, borderRadius: 'var(--r-lg)', padding: 26 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 4 }}>
            <span style={{ width: 36, height: 36, borderRadius: 10, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)', flexShrink: 0 }}>
              <Icons.Question size={18} />
            </span>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700 }}>Answer language</div>
              <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Choose the language DBeeLight replies in.</div>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 16 }}>
            {LANGUAGE_OPTIONS.map((opt) => {
              const selected = language === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setLanguage(opt.value)}
                  className="focusable"
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12, width: '100%', textAlign: 'left',
                    padding: '12px 14px', borderRadius: 'var(--r-sm)', cursor: 'pointer', transition: 'all .14s',
                    border: `1.5px solid ${selected ? 'var(--accent)' : 'var(--border)'}`,
                    background: selected ? 'var(--accent-soft)' : 'var(--surface)',
                  }}
                  onMouseEnter={(e) => { if (!selected) e.currentTarget.style.background = 'var(--surface-2)'; }}
                  onMouseLeave={(e) => { if (!selected) e.currentTarget.style.background = 'var(--surface)'; }}
                >
                  <span style={{ width: 20, height: 20, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', border: `2px solid ${selected ? 'var(--accent-strong)' : 'var(--border-strong)'}`, background: selected ? 'var(--accent-strong)' : 'transparent', color: 'var(--on-accent)' }}>
                    {selected && <Icons.Check size={13} />}
                  </span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: 'block', fontSize: 14.5, fontWeight: 600, color: selected ? 'var(--accent-ink)' : 'var(--text)' }}>{opt.label}</span>
                    <span style={{ display: 'block', fontSize: 12.5, color: 'var(--text-muted)' }}>{opt.sub}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

