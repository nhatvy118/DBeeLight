import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icons, type IconComponent } from '../icons';
import { toast } from '../components/Toaster';
import { confirm } from '../components/ConfirmDialog';
import { useAuth } from '../context/AuthContext';
import {
  url,
  getAdminOverview,
  adminInvite,
  adminRevokeInvite,
  adminSetUserRole,
  adminSetInviteRole,
  setUserDisabled,
  type AdminUser,
  type AdminInvite,
  type AdminStats,
  type AdminRole,
} from '../services/api';

function navigate(to: string) {
  window.history.pushState({}, '', to);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

/* ---- role identity (label / icon / colours) ---- */
type RoleMeta = { label: string; icon: IconComponent; tagline: string; desc: string; ink: string; soft: string; solid: string };
const ROLE_META: Record<AdminRole, RoleMeta> = {
  admin: {
    label: 'Admin', icon: Icons.ShieldUser, tagline: 'Runs the workspace',
    desc: 'Manages people and their roles across the workspace.',
    ink: 'oklch(0.48 0.15 285)', soft: 'oklch(0.95 0.035 285)', solid: 'oklch(0.55 0.16 285)',
  },
  technical: {
    label: 'Technical', icon: Icons.Code, tagline: 'Builds with data',
    desc: 'Connects databases, creates projects, full read & write.',
    ink: 'oklch(0.46 0.12 55)', soft: 'oklch(0.95 0.04 70)', solid: 'oklch(0.62 0.13 60)',
  },
  viewer: {
    label: 'Non-technical', icon: Icons.Eye, tagline: 'Explores in plain English',
    desc: 'Opens projects shared with them and asks questions. Read-only.',
    ink: 'oklch(0.44 0.1 155)', soft: 'oklch(0.95 0.04 155)', solid: 'oklch(0.56 0.12 155)',
  },
};
const ROLE_ORDER: AdminRole[] = ['admin', 'technical', 'viewer'];

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  } catch {
    return '—';
  }
}

/* ---- stat card ---- */
function StatCard({ icon: Icon, label, value, tint }: { icon: IconComponent; label: string; value: string | number; tint?: RoleMeta }) {
  return (
    <div className="card" style={{ padding: '16px 18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 10 }}>
        <span style={{ width: 32, height: 32, borderRadius: 9, display: 'grid', placeItems: 'center', background: tint ? tint.soft : 'var(--surface-2)', color: tint ? tint.ink : 'var(--text-soft)' }}>
          <Icon size={17} />
        </span>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-muted)' }}>{label}</span>
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: '-.02em' }}>{value}</div>
    </div>
  );
}

/* ---- role picker (used in the users table + invite rows) ---- */
function RoleDropdown({ value, disabled, onChange }: { value: AdminRole; disabled?: boolean; onChange: (r: AdminRole) => void }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const m = ROLE_META[value];
  const Icon = m.icon;

  const MENU_W = 240;
  const openMenu = () => {
    const r = btnRef.current?.getBoundingClientRect();
    if (r) setPos({ top: r.bottom + 6, left: Math.min(r.left, window.innerWidth - MENU_W - 12) });
    setOpen(true);
  };
  // Close on any scroll/resize so the menu never floats away from its button.
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => { window.removeEventListener('scroll', close, true); window.removeEventListener('resize', close); };
  }, [open]);

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={() => !disabled && (open ? setOpen(false) : openMenu())}
        disabled={disabled}
        className="focusable"
        style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderRadius: 99, border: '1px solid var(--border)', background: m.soft, color: m.ink, fontSize: 12.5, fontWeight: 700, cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.7 : 1 }}
      >
        <Icon size={14} /> {m.label}
        {!disabled && <Icons.ChevronDown size={13} style={{ transition: 'transform .15s', transform: open ? 'rotate(180deg)' : 'none' }} />}
      </button>
      {open && pos && createPortal(
        <>
          <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 300 }} />
          <div className="card pop-shadow" style={{ position: 'fixed', top: pos.top, left: pos.left, zIndex: 301, width: MENU_W, borderRadius: 'var(--r)', padding: 6 }}>
            {ROLE_ORDER.map((r) => {
              const rm = ROLE_META[r]; const RI = rm.icon; const sel = r === value;
              return (
                <button
                  key={r}
                  type="button"
                  onClick={() => { onChange(r); setOpen(false); }}
                  className="focusable"
                  style={{ width: '100%', display: 'flex', alignItems: 'flex-start', gap: 11, padding: '9px 10px', borderRadius: 'var(--r-sm)', textAlign: 'left', border: 'none', background: sel ? 'var(--surface-2)' : 'transparent', cursor: 'pointer' }}
                >
                  <span style={{ width: 30, height: 30, borderRadius: 8, flexShrink: 0, display: 'grid', placeItems: 'center', background: rm.soft, color: rm.ink }}><RI size={16} /></span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13.5, fontWeight: 700 }}>{rm.label}{sel && <Icons.Check size={14} style={{ color: 'var(--accent-ink)' }} />}</span>
                    <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.4, marginTop: 1 }}>{rm.tagline}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </>,
        document.body,
      )}
    </>
  );
}

/* ---- invite modal ---- */
function InviteModal({ onClose, onInvite }: { onClose: () => void; onInvite: (email: string, role: AdminRole) => Promise<void> }) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<AdminRole>('viewer');
  const [busy, setBusy] = useState(false);
  const send = async () => {
    if (!email.trim() || busy) return;
    setBusy(true);
    try { await onInvite(email.trim(), role); onClose(); }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Failed to send invite'); }
    finally { setBusy(false); }
  };
  return createPortal(
    <div className="backdrop" style={{ position: 'fixed', inset: 0, zIndex: 200, display: 'grid', placeItems: 'center', background: 'rgba(0,0,0,.4)', padding: 16 }} onClick={onClose}>
      <div className="card" style={{ width: 460, maxWidth: '100%', padding: 24, borderRadius: 'var(--r)' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <span style={{ width: 38, height: 38, borderRadius: 10, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}><Icons.Plus size={20} /></span>
          <div>
            <h3 style={{ fontSize: 18, fontWeight: 700 }}>Invite people</h3>
            <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>Only invited emails can sign in.</p>
          </div>
        </div>
        <label className="field-label" style={{ marginTop: 16 }}>Email address</label>
        <input className="field focusable" placeholder="name@company.com" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void send(); }} style={{ width: '100%' }} />
        <label className="field-label" style={{ marginTop: 18 }}>Role</label>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {ROLE_ORDER.map((r) => {
            const rm = ROLE_META[r]; const RI = rm.icon; const sel = r === role;
            return (
              <button key={r} type="button" onClick={() => setRole(r)} className="focusable"
                style={{ display: 'flex', alignItems: 'center', gap: 12, textAlign: 'left', padding: '12px 14px', borderRadius: 'var(--r-sm)', border: `1.5px solid ${sel ? 'var(--accent)' : 'var(--border)'}`, background: sel ? 'var(--accent-soft)' : 'var(--surface)', cursor: 'pointer' }}>
                <span style={{ width: 34, height: 34, borderRadius: 9, flexShrink: 0, display: 'grid', placeItems: 'center', background: rm.soft, color: rm.ink }}><RI size={17} /></span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: 'block', fontSize: 14, fontWeight: 700 }}>{rm.label}</span>
                  <span style={{ display: 'block', fontSize: 12.5, color: 'var(--text-muted)' }}>{rm.desc}</span>
                </span>
                <span style={{ width: 18, height: 18, borderRadius: 99, flexShrink: 0, border: `2px solid ${sel ? 'var(--accent-strong)' : 'var(--border-strong)'}`, display: 'grid', placeItems: 'center' }}>
                  {sel && <span style={{ width: 9, height: 9, borderRadius: 99, background: 'var(--accent-strong)' }} />}
                </span>
              </button>
            );
          })}
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
          <button type="button" className="btn btn-outline" style={{ flex: '0 0 auto', padding: '12px 20px' }} onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" style={{ flex: 1, padding: '12px 20px' }} disabled={!email.trim() || busy} onClick={() => void send()}>
            <Icons.Send size={16} /> {busy ? 'Sending…' : 'Send invite'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default function AdminDashboard() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [invites, setInvites] = useState<AdminInvite[]>([]);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [busyId, setBusyId] = useState<number | null>(null);
  const [showInvite, setShowInvite] = useState(false);
  const { user, setUser } = useAuth();

  const signOut = async () => {
    try { await fetch(url('/api/auth/logout'), { method: 'POST', credentials: 'include' }); } catch { /* clear locally anyway */ }
    setUser(null);
    navigate('/login');
  };

  const load = async () => {
    setIsLoading(true); setError(null);
    try {
      const o = await getAdminOverview();
      setUsers(o.users); setInvites(o.invites); setStats(o.stats);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load admin data');
    } finally {
      setIsLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);

  const counts = useMemo(() => {
    const c = { admin: 0, technical: 0, viewer: 0 };
    users.forEach((u) => { c[u.role]++; });
    return c;
  }, [users]);
  const total = users.length;
  const disabledCount = users.filter((u) => u.status === 'disabled').length;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return users;
    return users.filter((u) => (u.name ?? '').toLowerCase().includes(q) || (u.email ?? '').toLowerCase().includes(q));
  }, [users, query]);

  const handleSetUserRole = async (u: AdminUser, role: AdminRole) => {
    if (role === u.role) return;
    const prev = u.role;
    setUsers((us) => us.map((x) => (x.id === u.id ? { ...x, role } : x)));
    try { await adminSetUserRole(u.id, role); }
    catch (e) {
      setUsers((us) => us.map((x) => (x.id === u.id ? { ...x, role: prev } : x)));
      toast.error(e instanceof Error ? e.message : 'Failed to change role');
    }
  };

  const handleSetInviteRole = async (inv: AdminInvite, role: AdminRole) => {
    if (role === inv.role) return;
    const prev = inv.role;
    setInvites((is) => is.map((x) => (x.id === inv.id ? { ...x, role } : x)));
    try { await adminSetInviteRole(inv.id, role); }
    catch (e) {
      setInvites((is) => is.map((x) => (x.id === inv.id ? { ...x, role: prev } : x)));
      toast.error(e instanceof Error ? e.message : 'Failed to update invite');
    }
  };

  const handleRevoke = async (inv: AdminInvite) => {
    if (!(await confirm({ title: 'Revoke invite?', message: `Revoke the invite for ${inv.email}? They will no longer be able to sign in.`, confirmLabel: 'Revoke', danger: true }))) return;
    try { await adminRevokeInvite(inv.id); setInvites((is) => is.filter((x) => x.id !== inv.id)); }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Failed to revoke invite'); }
  };

  const handleInvite = async (email: string, role: AdminRole) => {
    const inv = await adminInvite(email, role);
    setInvites((is) => [...is.filter((x) => x.id !== inv.id), inv]);
    toast.success(`Invited ${email}`);
  };

  const handleToggleDisabled = async (u: AdminUser) => {
    const disable = u.status === 'active';
    if (disable && !(await confirm({ title: 'Disable account?', message: `Disable ${u.name || u.email || 'this user'}? They won't be able to sign in.`, confirmLabel: 'Disable', danger: true }))) return;
    setBusyId(u.id);
    try {
      const disabled = await setUserDisabled(u.id, disable);
      setUsers((us) => us.map((x) => (x.id === u.id ? { ...x, status: disabled ? 'disabled' : 'active' } : x)));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to update user');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'var(--bg)' }}>
      <div style={{ maxWidth: 1080, margin: '0 auto', padding: '24px 22px 60px' }}>
        {/* header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 18, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 15.5, fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 9 }}>
            <Icons.ShieldUser size={18} style={{ color: ROLE_META.admin.ink }} /> Admin · People &amp; roles
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button type="button" className="btn btn-outline focusable" style={{ padding: '8px 12px' }} onClick={() => void load()} disabled={isLoading}>
              <Icons.Refresh size={15} /> Refresh
            </button>
            <button type="button" className="btn btn-primary focusable" style={{ padding: '8px 14px' }} onClick={() => setShowInvite(true)}>
              <Icons.Plus size={16} /> Invite people
            </button>
            <div style={{ width: 1, height: 24, background: 'var(--border)', margin: '0 4px' }} />
            {user?.email && (
              <span title={user.email} style={{ fontSize: 13, color: 'var(--text-muted)', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.email}</span>
            )}
            <button type="button" className="btn btn-outline focusable" title="Sign out" style={{ padding: '8px 12px' }} onClick={() => void signOut()}>
              <Icons.Logout size={15} /> Sign out
            </button>
          </div>
        </div>

        <div style={{ marginBottom: 18 }}>
          <h1 style={{ fontSize: 24, fontWeight: 800, letterSpacing: '-.02em' }}>People &amp; roles</h1>
          <p style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 4 }}>Assign each person a role. Roles decide what they can do across the workspace.</p>
        </div>

        {/* stat cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 14 }}>
          <StatCard icon={Icons.Users} label="Total people" value={total} />
          <StatCard icon={ROLE_META.admin.icon} label="Admins" value={counts.admin} tint={ROLE_META.admin} />
          <StatCard icon={ROLE_META.technical.icon} label="Technical" value={counts.technical} tint={ROLE_META.technical} />
          <StatCard icon={ROLE_META.viewer.icon} label="Non-technical" value={counts.viewer} tint={ROLE_META.viewer} />
          <StatCard icon={Icons.Stop} label="Disabled" value={disabledCount} />
          <StatCard icon={Icons.Send} label="Pending invites" value={invites.length} />
        </div>

        {/* workspace by role */}
        <div className="card" style={{ padding: '18px 20px', marginBottom: 24 }}>
          <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 16 }}>Workspace by role</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
            {ROLE_ORDER.map((r) => {
              const rm = ROLE_META[r]; const c = counts[r]; const pct = total ? Math.round((c / total) * 100) : 0; const RI = rm.icon;
              return (
                <div key={r} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 44px', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-soft)', display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                    <RI size={15} style={{ color: rm.ink }} />{rm.label}
                  </span>
                  <div style={{ height: 12, borderRadius: 99, background: 'var(--surface-3)', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${pct}%`, background: rm.solid, borderRadius: 99, transition: 'width .3s' }} />
                  </div>
                  <span style={{ fontSize: 13, fontWeight: 700, textAlign: 'right' }}>{c}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* pending invites */}
        {invites.length > 0 && (
          <div style={{ marginBottom: 24 }}>
            <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>Pending invites ({invites.length})</h2>
            <div className="card" style={{ overflow: 'hidden' }}>
              {invites.map((inv, i) => (
                <div key={inv.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', borderTop: i ? '1px solid var(--border)' : 'none' }}>
                  <span style={{ width: 32, height: 32, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--surface-2)', color: 'var(--text-faint)' }}><Icons.Send size={15} /></span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: 'block', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{inv.email}</span>
                    <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)' }}>Invited {formatDate(inv.created_at)} · awaiting first sign-in</span>
                  </span>
                  <RoleDropdown value={inv.role} onChange={(r) => void handleSetInviteRole(inv, r)} />
                  <button type="button" className="focusable" title="Revoke invite" onClick={() => void handleRevoke(inv)} style={{ width: 32, height: 32, borderRadius: 8, display: 'grid', placeItems: 'center', border: 'none', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer' }}>
                    <Icons.Trash size={16} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* users */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
          <h2 style={{ fontSize: 16, fontWeight: 700 }}>Users</h2>
          <div style={{ position: 'relative', width: 280, maxWidth: '100%' }}>
            <Icons.Search size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-faint)' }} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search people…" className="field focusable" style={{ width: '100%', paddingLeft: 36 }} />
          </div>
        </div>

        <div className="card" style={{ overflow: 'hidden' }}>
          {isLoading ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
          ) : error ? (
            <div style={{ padding: 32, textAlign: 'center' }}>
              <div style={{ color: 'var(--danger)', fontWeight: 600 }}>{error}</div>
              <button type="button" className="btn btn-outline" style={{ marginTop: 12 }} onClick={() => void load()}>Try again</button>
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>No people found.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13.5 }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: 'var(--text-faint)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em' }}>
                    <th style={{ padding: '12px 16px', fontWeight: 700 }}>Person</th>
                    <th style={{ padding: '12px 12px', fontWeight: 700 }}>Role</th>
                    <th style={{ padding: '12px 12px', fontWeight: 700 }}>Joined</th>
                    <th style={{ padding: '12px 12px', fontWeight: 700, textAlign: 'right' }}>Projects</th>
                    <th style={{ padding: '12px 12px', fontWeight: 700 }}>Status</th>
                    <th style={{ padding: '12px 16px', fontWeight: 700, textAlign: 'right' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((u) => (
                    <tr key={u.id} style={{ borderTop: '1px solid var(--border)', opacity: u.status === 'disabled' ? 0.55 : 1 }}>
                      <td style={{ padding: '12px 16px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ width: 32, height: 32, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)', fontSize: 12.5, fontWeight: 800 }}>
                            {(u.name || u.email || '?')[0]?.toUpperCase()}
                          </span>
                          <span style={{ minWidth: 0 }}>
                            <span style={{ display: 'flex', alignItems: 'center', gap: 7, fontWeight: 600 }}>
                              {u.name || '—'}
                              {u.is_self && <span style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-faint)', border: '1px solid var(--border)', borderRadius: 99, padding: '1px 7px' }}>You</span>}
                            </span>
                            <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 220 }}>{u.email || '—'}</span>
                          </span>
                        </div>
                      </td>
                      <td style={{ padding: '12px 12px' }}>
                        <RoleDropdown value={u.role} disabled={u.is_self} onChange={(r) => void handleSetUserRole(u, r)} />
                      </td>
                      <td style={{ padding: '12px 12px', color: 'var(--text-soft)', whiteSpace: 'nowrap' }}>{formatDate(u.created_at)}</td>
                      <td style={{ padding: '12px 12px', textAlign: 'right', color: 'var(--text-soft)' }}>{u.project_count}</td>
                      <td style={{ padding: '12px 12px' }}>
                        {u.status === 'disabled' ? (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5, fontWeight: 700, color: 'oklch(0.55 0.17 25)', background: 'oklch(0.95 0.04 25)', borderRadius: 99, padding: '2px 9px' }}>
                            <span style={{ width: 6, height: 6, borderRadius: 99, background: 'oklch(0.6 0.18 25)' }} /> Disabled
                          </span>
                        ) : (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5, fontWeight: 700, color: 'var(--green-ink, #1a7f37)', background: 'var(--green-soft, #e6f4ea)', borderRadius: 99, padding: '2px 9px' }}>
                            <span style={{ width: 6, height: 6, borderRadius: 99, background: 'var(--green, #2e9e5b)' }} /> Active
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                        <button
                          type="button"
                          className="btn focusable"
                          disabled={busyId === u.id || u.is_self}
                          title={u.is_self ? "You can't disable your own account" : undefined}
                          onClick={() => void handleToggleDisabled(u)}
                          style={{ padding: '6px 12px', fontSize: 13, fontWeight: 700, border: '1px solid var(--border)', background: u.status === 'disabled' ? 'var(--accent)' : 'transparent', color: u.status === 'disabled' ? 'var(--on-accent)' : 'var(--danger-ink)', cursor: (busyId === u.id || u.is_self) ? 'not-allowed' : 'pointer', opacity: u.is_self ? 0.4 : 1 }}
                        >
                          {busyId === u.id ? '…' : u.status === 'disabled' ? 'Enable' : 'Disable'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
      {showInvite && <InviteModal onClose={() => setShowInvite(false)} onInvite={handleInvite} />}
    </div>
  );
}
