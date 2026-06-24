import { useEffect, useState } from 'react';
import { Icons, BeeBadge } from '../icons';
import { useAuth } from '../context/AuthContext';
import Chat from './Chat';
import Dashboard from './Dashboard';
import { url, listSharedProjects, type SharedProject } from '../services/api';

/**
 * Dedicated UI for the non-technical (viewer) role: projects shared with them, with a read-only
 * chat (multiple sessions, like the technical user) and a personal Dashboard of saved charts per
 * project. Rendered full-screen (no app chrome) like admin. Writes are refused by the backend.
 */
export default function ViewerApp() {
  const { user, setUser } = useAuth();
  const [projects, setProjects] = useState<SharedProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [view, setView] = useState<'chat' | 'dashboard'>('chat');

  // The URL reflects the open project + view: /chat/:pid(/:sid) or /dashboard/:pid.
  const openProject = (id: string) => { window.history.pushState({}, '', `/chat/${id}`); setOpenId(id); setSessionId(null); setView('chat'); };
  const openDashboard = (id: string) => { window.history.pushState({}, '', `/dashboard/${id}`); setOpenId(id); setView('dashboard'); };
  const goHome = () => { window.history.pushState({}, '', '/chat'); setOpenId(null); setSessionId(null); setView('chat'); };

  // Sync state from the URL on mount + back/forward.
  useEffect(() => {
    const sync = () => {
      const parts = window.location.pathname.split('/').filter(Boolean);
      if (parts[0] === 'dashboard' && parts[1]) { setOpenId(parts[1]); setView('dashboard'); setSessionId(null); }
      else if (parts[0] === 'chat' && parts[1]) { setOpenId(parts[1]); setView('chat'); setSessionId(parts[2] || null); }
      else { setOpenId(null); setView('chat'); setSessionId(null); }
    };
    sync();
    window.addEventListener('popstate', sync);
    return () => window.removeEventListener('popstate', sync);
  }, []);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const shared = await listSharedProjects();
      setProjects(shared);
      // Cache for Chat/Dashboard's fast-path project lookup (same 'projects' key the technical
      // sidebar uses), so a shared project resolves from cache without a per-project API fallback.
      try {
        localStorage.setItem('projects', JSON.stringify(
          shared.map((p) => ({ id: p.id, name: p.name, description: p.description })),
        ));
      } catch { /* storage disabled — the getProject fallback still covers it */ }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load shared projects');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);

  const signOut = async () => {
    try { await fetch(url('/api/auth/logout'), { method: 'POST', credentials: 'include' }); } catch { /* clear locally anyway */ }
    setUser(null);
    window.history.pushState({}, '', '/login');
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  const onSession = (sid: string | null) => setSessionId(sid);
  const open = projects.find((p) => p.id === openId) || null;
  const initial = (user?.name || user?.email || '?')[0]?.toUpperCase();

  return (
    <div style={{ display: 'flex', height: '100%', background: 'var(--bg)' }}>
      {/* sidebar — switch between shared projects (and chat/dashboard per project) */}
      <aside style={{ width: 286, flexShrink: 0, height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--surface-2)', borderRight: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '16px 18px' }}>
          <BeeBadge size={36} />
          <span style={{ fontSize: 19, fontWeight: 800, letterSpacing: '-.02em' }}>LightDBee</span>
        </div>

        <button
          type="button"
          onClick={goHome}
          className="focusable"
          style={{ margin: '6px 14px 4px', display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px', borderRadius: 'var(--r-sm)', fontSize: 14.5, fontWeight: 700, cursor: 'pointer', border: '1px solid transparent', background: openId === null ? 'var(--accent-soft)' : 'transparent', color: openId === null ? 'var(--accent-ink)' : 'var(--text-soft)' }}
        >
          <Icons.Share size={18} /> Shared with me
        </button>

        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px' }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-faint)', padding: '0 12px', marginBottom: 8 }}>Projects ({projects.length})</div>
          {projects.map((pr) => {
            const on = openId === pr.id;
            return (
              <div key={pr.id} style={{ position: 'relative', marginBottom: 2 }}>
                <button
                  type="button"
                  onClick={() => openProject(pr.id)}
                  className="focusable"
                  style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 11, padding: '10px 36px 10px 12px', borderRadius: 'var(--r-sm)', textAlign: 'left', cursor: 'pointer', border: '1px solid ' + (on ? 'var(--border)' : 'transparent'), background: on ? 'var(--surface)' : 'transparent', color: on ? 'var(--text)' : 'var(--text-soft)' }}
                >
                  <span style={{ width: 30, height: 30, borderRadius: 8, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}><Icons.Folder size={16} /></span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: 'block', fontSize: 13.5, fontWeight: on ? 700 : 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pr.name}</span>
                    <span style={{ display: 'block', fontSize: 11.5, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>from {pr.owner_name || pr.owner_email || '—'}</span>
                  </span>
                </button>
                <button type="button" onClick={(e) => { e.stopPropagation(); openDashboard(pr.id); }} title="Dashboard" className="focusable" style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', width: 26, height: 26, display: 'grid', placeItems: 'center', borderRadius: 6, border: 'none', background: 'transparent', color: (on && view === 'dashboard') ? 'var(--accent-ink)' : 'var(--text-faint)', cursor: 'pointer' }}>
                  <Icons.Chart size={15} />
                </button>
              </div>
            );
          })}
          {!loading && projects.length === 0 && <p style={{ fontSize: 12.5, color: 'var(--text-muted)', padding: '8px 12px' }}>No projects shared with you yet.</p>}
        </div>

        {/* profile + sign out */}
        <div style={{ borderTop: '1px solid var(--border)', padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 11 }}>
          <div style={{ width: 36, height: 36, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'linear-gradient(145deg, var(--accent), var(--accent-strong))', color: 'var(--on-accent)', fontWeight: 800 }}>{initial}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13.5, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user?.name || user?.email}</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center', gap: 5 }}><Icons.Eye size={12} /> Non-technical</div>
          </div>
          <button type="button" onClick={() => void signOut()} title="Sign out" className="focusable" style={{ width: 32, height: 32, borderRadius: 8, display: 'grid', placeItems: 'center', border: 'none', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer' }}><Icons.Logout size={16} /></button>
        </div>
      </aside>

      {/* main — home grid, the read-only chat, or the personal dashboard */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {open ? (
          view === 'dashboard'
            ? <Dashboard key={`d:${open.id}`} projectId={open.id} />
            : <Chat key={`c:${open.id}`} projectId={open.id} sessionId={sessionId} viewer onSessionIdChange={onSession} />
        ) : (
          <div style={{ flex: 1, overflowY: 'auto', padding: '44px 24px 60px' }}>
            <div style={{ maxWidth: 880, margin: '0 auto' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, fontWeight: 700, padding: '5px 12px', borderRadius: 99, background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}><Icons.Eye size={15} /> Non-technical</span>
              <h1 style={{ fontSize: 32, fontWeight: 800, letterSpacing: '-.025em', marginTop: 10 }}>Shared with you</h1>
              <p style={{ fontSize: 17, color: 'var(--text-soft)', marginTop: 8 }}>Open a project to explore its data — just ask questions in plain English.</p>
              {error && <p style={{ color: 'var(--danger)', marginTop: 16 }}>{error}</p>}
              {loading ? (
                <p style={{ color: 'var(--text-muted)', marginTop: 24 }}>Loading…</p>
              ) : projects.length === 0 ? (
                <div className="card" style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', marginTop: 24 }}>Nothing shared with you yet. Ask a teammate to share a project.</div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginTop: 30 }}>
                  {projects.map((pr) => (
                    <button key={pr.id} type="button" onClick={() => openProject(pr.id)} className="card focusable" style={{ textAlign: 'left', padding: 20, borderRadius: 'var(--r-lg)', cursor: 'pointer' }}>
                      <span style={{ width: 46, height: 46, borderRadius: 13, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}><Icons.Folder size={23} /></span>
                      <div style={{ fontSize: 17, fontWeight: 700, marginTop: 14 }}>{pr.name}</div>
                      <p style={{ fontSize: 13.5, color: 'var(--text-muted)', marginTop: 5, lineHeight: 1.5, minHeight: 40 }}>{pr.description || '—'}</p>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)', fontSize: 12.5, color: 'var(--text-soft)', fontWeight: 600 }}>
                        from {pr.owner_name || pr.owner_email || '—'}
                        <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 5, color: 'var(--text-muted)' }}><Icons.Eye size={14} />View</span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
