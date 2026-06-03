import { useEffect, useMemo, useState } from 'react';
import { Icons, type IconComponent } from '../icons';
import { toast } from '../components/Toaster';
import { confirm } from '../components/ConfirmDialog';
import { useAuth } from '../context/AuthContext';
import {
  getAdminUsers,
  getAdminStats,
  setUserDisabled,
  type AdminUser,
  type AdminStats,
} from '../services/api';

function navigate(to: string) {
  window.history.pushState({}, '', to);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

function formatBytes(n: number): string {
  if (!n) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  } catch {
    return '—';
  }
}

function StatCard({ icon: Icon, label, value }: { icon: IconComponent; label: string; value: string | number }) {
  return (
    <div className="card" style={{ padding: '16px 18px' }}>
      <span style={{ width: 38, height: 38, borderRadius: 10, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}>
        <Icon size={19} />
      </span>
      <div style={{ fontSize: 26, fontWeight: 800, marginTop: 12, lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 5 }}>{label}</div>
    </div>
  );
}

function RoleBar({ label, count, total, color }: { label: string; count: number; total: number; color: string }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
        <span style={{ fontWeight: 600, color: 'var(--text)' }}>{label}</span>
        <span style={{ color: 'var(--text-muted)', fontWeight: 600 }}>{count}</span>
      </div>
      <div style={{ height: 8, borderRadius: 99, background: 'var(--surface-3)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', borderRadius: 99, background: color, transition: 'width .4s' }} />
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const { user } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [u, s] = await Promise.all([getAdminUsers(), getAdminStats()]);
      setUsers(u);
      setStats(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load admin data');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return users;
    return users.filter((u) =>
      (u.name ?? '').toLowerCase().includes(q) || (u.email ?? '').toLowerCase().includes(q),
    );
  }, [users, query]);

  // Real sign-ups per week for the last 8 weeks, from each user's created_at.
  const weeks = useMemo(() => {
    const MS_WEEK = 7 * 24 * 3600 * 1000;
    const start = new Date().getTime() - 8 * MS_WEEK;
    const buckets = Array.from({ length: 8 }, () => 0);
    for (const u of users) {
      if (!u.created_at) continue;
      const t = new Date(u.created_at).getTime();
      if (Number.isNaN(t) || t < start) continue;
      buckets[Math.min(7, Math.floor((t - start) / MS_WEEK))]++;
    }
    return buckets;
  }, [users]);
  const maxWeek = Math.max(1, ...weeks);

  const handleToggle = async (u: AdminUser) => {
    const next = !u.disabled;
    if (next && !(await confirm({ title: 'Disable account?', message: `Disable ${u.name || u.email || 'this user'}? They won't be able to sign in.`, confirmLabel: 'Disable', danger: true }))) return;
    setBusyId(u.id);
    try {
      const disabled = await setUserDisabled(u.id, next);
      setUsers((prev) => prev.map((x) => (x.id === u.id ? { ...x, disabled } : x)));
      setStats((prev) => prev ? { ...prev, disabled_users: prev.disabled_users + (disabled ? 1 : -1) } : prev);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to update user');
    } finally {
      setBusyId(null);
    }
  };

  const totalUsers = stats?.total_users ?? users.length;
  const adminCount = stats?.admin_users ?? 0;
  const disabledCount = stats?.disabled_users ?? 0;
  const memberCount = Math.max(0, totalUsers - adminCount);

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'var(--bg)' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '24px 22px 60px' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 22 }}>
          <button type="button" className="btn btn-outline focusable" style={{ padding: '8px 12px' }} onClick={() => navigate('/chat')}>
            <Icons.ChevronRight size={16} style={{ transform: 'rotate(180deg)' }} /> Back
          </button>
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-.01em' }}>Admin · Users</h1>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 2 }}>Manage accounts and review platform usage.</p>
          </div>
          <button type="button" className="btn btn-outline focusable" style={{ padding: '8px 12px' }} onClick={() => void load()} disabled={isLoading}>
            <Icons.Refresh size={15} /> Refresh
          </button>
        </div>

        {/* Stat cards */}
        {stats && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(155px, 1fr))', gap: 12, marginBottom: 16 }}>
            <StatCard icon={Icons.Users} label="Total users" value={stats.total_users} />
            <StatCard icon={Icons.Stop} label="Disabled" value={stats.disabled_users} />
            <StatCard icon={Icons.ShieldUser} label="Admins" value={stats.admin_users} />
            <StatCard icon={Icons.Folder} label="Projects" value={stats.total_projects} />
            <StatCard icon={Icons.NewChat} label="Sessions" value={stats.total_sessions} />
            <StatCard icon={Icons.HardDrive} label="Storage" value={formatBytes(stats.total_storage_bytes)} />
          </div>
        )}

        {/* Charts row */}
        {stats && (
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)', gap: 12, marginBottom: 24 }}>
            <div className="card" style={{ padding: '18px 20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
                <h2 style={{ fontSize: 15, fontWeight: 700 }}>New sign-ups</h2>
                <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>Last 8 weeks</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 120 }}>
                {weeks.map((c, i) => (
                  <div key={i} title={`${c} sign-up${c === 1 ? '' : 's'}`} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%' }}>
                    <div style={{ height: `${Math.max(6, (c / maxWeek) * 100)}%`, borderRadius: '6px 6px 3px 3px', background: i === 7 ? 'var(--accent-strong)' : 'var(--accent-soft-2)' }} />
                  </div>
                ))}
              </div>
            </div>
            <div className="card" style={{ padding: '18px 20px' }}>
              <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 16 }}>By role &amp; status</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <RoleBar label="Admins" count={adminCount} total={totalUsers} color="var(--accent-strong)" />
                <RoleBar label="Members" count={memberCount} total={totalUsers} color="var(--green, #2e9e5b)" />
                <RoleBar label="Disabled" count={disabledCount} total={totalUsers} color="var(--danger)" />
              </div>
            </div>
          </div>
        )}

        {/* Users section */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
          <div>
            <h2 style={{ fontSize: 16, fontWeight: 700 }}>Users</h2>
            <p style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>Manage members and access.</p>
          </div>
          <div style={{ position: 'relative', width: 300, maxWidth: '100%' }}>
            <Icons.Search size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-faint)' }} />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search users…"
              className="field focusable"
              style={{ width: '100%', paddingLeft: 36 }}
            />
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
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>No users found.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13.5 }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: 'var(--text-faint)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em' }}>
                    <th style={{ padding: '12px 16px', fontWeight: 700 }}>User</th>
                    <th style={{ padding: '12px 12px', fontWeight: 700 }}>Role</th>
                    <th style={{ padding: '12px 12px', fontWeight: 700 }}>Joined</th>
                    <th style={{ padding: '12px 12px', fontWeight: 700, textAlign: 'right' }}>Projects</th>
                    <th style={{ padding: '12px 12px', fontWeight: 700, textAlign: 'right' }}>Sessions</th>
                    <th style={{ padding: '12px 12px', fontWeight: 700, textAlign: 'right' }}>Storage</th>
                    <th style={{ padding: '12px 12px', fontWeight: 700 }}>Status</th>
                    <th style={{ padding: '12px 16px', fontWeight: 700, textAlign: 'right' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((u) => {
                    const self = !!(user?.email && u.email && user.email.toLowerCase() === u.email.toLowerCase());
                    return (
                      <tr key={u.id} style={{ borderTop: '1px solid var(--border)', opacity: u.disabled ? 0.6 : 1 }}>
                        <td style={{ padding: '12px 16px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <span style={{ width: 32, height: 32, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)', fontSize: 12.5, fontWeight: 800 }}>
                              {(u.name || u.email || '?')[0]?.toUpperCase()}
                            </span>
                            <span style={{ minWidth: 0 }}>
                              <span style={{ display: 'block', fontWeight: 600, color: 'var(--text)' }}>{u.name || '—'}</span>
                              <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 220 }}>{u.email || '—'}</span>
                            </span>
                          </div>
                        </td>
                        <td style={{ padding: '12px 12px' }}>
                          {u.is_admin ? (
                            <span style={{ fontWeight: 700, color: 'var(--accent-ink)' }}>Admin</span>
                          ) : (
                            <span style={{ color: 'var(--text-soft)' }}>Member</span>
                          )}
                        </td>
                        <td style={{ padding: '12px 12px', color: 'var(--text-soft)', whiteSpace: 'nowrap' }}>{formatDate(u.created_at)}</td>
                        <td style={{ padding: '12px 12px', textAlign: 'right', color: 'var(--text-soft)' }}>{u.project_count}</td>
                        <td style={{ padding: '12px 12px', textAlign: 'right', color: 'var(--text-soft)' }}>{u.session_count}</td>
                        <td style={{ padding: '12px 12px', textAlign: 'right', color: 'var(--text-soft)', whiteSpace: 'nowrap' }}>{formatBytes(u.storage_bytes)}</td>
                        <td style={{ padding: '12px 12px' }}>
                          {u.disabled ? (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5, fontWeight: 700, color: 'var(--danger-ink)', background: 'var(--danger-soft)', borderRadius: 99, padding: '2px 9px' }}>
                              <span style={{ width: 6, height: 6, borderRadius: 99, background: 'var(--danger)' }} /> Disabled
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
                            disabled={busyId === u.id || self}
                            title={self ? "You can't disable your own account" : undefined}
                            onClick={() => void handleToggle(u)}
                            style={{ padding: '6px 12px', fontSize: 13, fontWeight: 700,
                              border: '1px solid var(--border)',
                              background: u.disabled ? 'var(--accent)' : 'transparent',
                              color: u.disabled ? 'var(--on-accent)' : 'var(--danger-ink)',
                              cursor: (busyId === u.id || self) ? 'not-allowed' : 'pointer',
                              opacity: self ? 0.4 : 1 }}
                          >
                            {busyId === u.id ? '…' : u.disabled ? 'Enable' : 'Disable'}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
