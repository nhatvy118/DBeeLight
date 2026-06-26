import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icons } from '../../icons';
import { toast } from '../Toaster';
import {
  listProjectShares, listShareableUsers, shareProject, unshareProject, setSharePermission,
  type ProjectShare, type ShareableUser, type SharePermission,
} from '../../services/api';

/** view/edit picker shown for technical teammates (viewers are locked to view). */
function AccessPicker({ value, onChange }: { value: SharePermission; onChange: (p: SharePermission) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const opts: { k: SharePermission; label: string; d: string }[] = [
    { k: 'edit', label: 'Can edit', d: 'Query and change this data' },
    { k: 'view', label: 'Can view', d: 'Explore — read only' },
  ];
  const cur = opts.find((o) => o.k === value) || opts[1];

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button type="button" onClick={() => setOpen((o) => !o)} className="focusable"
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 9px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', fontSize: 12, fontWeight: 600, color: 'var(--text-soft)', cursor: 'pointer' }}>
        {cur.label}<Icons.ChevronDown size={13} style={{ color: 'var(--text-faint)' }} />
      </button>
      {open && (
        <div className="card pop-shadow" style={{ position: 'absolute', top: 'calc(100% + 6px)', right: 0, zIndex: 51, width: 214, borderRadius: 'var(--r)', padding: 6 }}>
          {opts.map((o) => {
            const sel = o.k === value;
            return (
              <button key={o.k} type="button" onClick={() => { onChange(o.k); setOpen(false); }} className="focusable"
                style={{ width: '100%', display: 'flex', alignItems: 'flex-start', gap: 8, padding: '8px 9px', borderRadius: 'var(--r-sm)', textAlign: 'left', border: 'none', background: sel ? 'var(--surface-2)' : 'transparent', cursor: 'pointer' }}>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 700 }}>{o.label}{sel && <Icons.Check size={13} style={{ color: 'var(--accent-ink)' }} />}</span>
                  <span style={{ display: 'block', fontSize: 11.5, color: 'var(--text-muted)' }}>{o.d}</span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Technical owner shares a project's DATA (read-only) with an existing user — pick from a list
 * or type an email. */
export default function ShareProjectModal({ project, onClose }: { project: { id: string; name: string }; onClose: () => void }) {
  const [shares, setShares] = useState<ProjectShare[]>([]);
  const [candidates, setCandidates] = useState<ShareableUser[]>([]);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  // The pick-list behaves like a search autocomplete: hidden until the input is
  // focused, then filters as the user types. Closes when focus leaves the field.
  const [focused, setFocused] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [s, c] = await Promise.all([listProjectShares(project.id), listShareableUsers(project.id)]);
      setShares(s); setCandidates(c);
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Failed to load'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [project.id]);

  const doShare = async (addr: string) => {
    if (!addr.trim() || busy) return;
    setBusy(true);
    try {
      const s = await shareProject(project.id, addr.trim());
      setShares((p) => [...p.filter((x) => x.user_id !== s.user_id), s]);
      setCandidates((c) => c.filter((u) => u.user_id !== s.user_id));
      setEmail('');
      toast.success(`Shared with ${s.email}`);
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Failed to share'); }
    finally { setBusy(false); }
  };

  const remove = async (s: ProjectShare) => {
    try {
      await unshareProject(project.id, s.user_id);
      setShares((p) => p.filter((x) => x.user_id !== s.user_id));
      setCandidates((c) => [...c, { user_id: s.user_id, name: s.name, email: s.email, role: s.role }]);
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Failed to remove access'); }
  };

  const setPerm = async (s: ProjectShare, perm: SharePermission) => {
    if (perm === s.permission) return;
    const prev = s.permission;
    setShares((list) => list.map((x) => (x.user_id === s.user_id ? { ...x, permission: perm } : x)));
    try {
      const eff = await setSharePermission(project.id, s.user_id, perm);
      setShares((list) => list.map((x) => (x.user_id === s.user_id ? { ...x, permission: eff } : x)));
      if (eff !== perm) toast.error('Only technical teammates can be given edit access');
    } catch (e) {
      setShares((list) => list.map((x) => (x.user_id === s.user_id ? { ...x, permission: prev } : x)));
      toast.error(e instanceof Error ? e.message : 'Failed to update access');
    }
  };

  // Pick-list source: never offer admins as share targets.
  const shareable = useMemo(() => candidates.filter((u) => u.role !== 'admin'), [candidates]);

  // Filter the pick-list by what's typed (name or email).
  const filtered = useMemo(() => {
    const q = email.trim().toLowerCase();
    const list = q ? shareable.filter((u) => (u.name || '').toLowerCase().includes(q) || (u.email || '').toLowerCase().includes(q)) : shareable;
    return list.slice(0, 50);
  }, [shareable, email]);

  return createPortal(
    <div className="backdrop" style={{ position: 'fixed', inset: 0, zIndex: 200, display: 'grid', placeItems: 'center', background: 'rgba(0,0,0,.4)', padding: 16 }} onClick={onClose}>
      <div className="card" style={{ width: 540, maxWidth: '100%', padding: 24, borderRadius: 'var(--r)' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <span style={{ width: 38, height: 38, borderRadius: 10, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}><Icons.Share size={19} /></span>
          <div style={{ minWidth: 0 }}>
            <h3 style={{ fontSize: 18, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>Share this project</h3>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{project.name}</p>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '11px 13px', background: 'var(--surface-2)', borderRadius: 'var(--r-sm)', margin: '14px 0 18px' }}>
          <Icons.Database size={16} style={{ color: 'var(--text-muted)', flexShrink: 0, marginTop: 1 }} />
          <span style={{ fontSize: 12.5, lineHeight: 1.5, color: 'var(--text-soft)' }}>
            Sharing gives people <strong>read-only</strong> access to this project's <strong>data</strong> — not your chats.
          </span>
        </div>

        {/* search / type email */}
        <label className="field-label">Pick a teammate or type their email</label>
        <div style={{ display: 'flex', gap: 8 }}>
          {/* relative wrapper around the input only, so the dropdown matches its width */}
          <div style={{ position: 'relative', flex: 1 }}>
            <input className="field focusable" placeholder="Search name or email…" value={email} style={{ width: '100%' }}
              onFocus={() => setFocused(true)}
              // Delay so a click on a pick-list row registers before the list unmounts.
              onBlur={() => setTimeout(() => setFocused(false), 120)}
              onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && email.includes('@')) void doShare(email); }} />

            {/* clickable pick-list — only while the search field is focused */}
            {focused && (
              <div className="card pop-shadow" style={{ position: 'absolute', top: 'calc(100% + 6px)', left: 0, right: 0, zIndex: 10, overflow: 'hidden', maxHeight: 240, overflowY: 'auto' }}>
                {loading ? (
                  <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>Loading…</div>
                ) : filtered.length === 0 ? (
                  <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                    {shareable.length === 0 ? 'Everyone with an account already has access.' : 'No match — type the full email to invite.'}
                  </div>
                ) : filtered.map((u, i) => (
                  <button key={u.user_id} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => { setEmail(u.email || ''); setFocused(false); }} disabled={busy} className="focusable"
                    style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 11, padding: '10px 14px', borderTop: i ? '1px solid var(--border)' : 'none', border: 'none', background: 'transparent', textAlign: 'left', cursor: 'pointer' }}>
                    <span style={{ width: 32, height: 32, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--surface-3)', color: 'var(--text-soft)', fontSize: 12.5, fontWeight: 800 }}>{(u.name || u.email || '?')[0]?.toUpperCase()}</span>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ display: 'block', fontSize: 13.5, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{u.name || u.email}</span>
                      <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{u.email}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <button type="button" className="btn btn-primary" style={{ padding: '12px 18px' }} disabled={!email.includes('@') || busy} onClick={() => void doShare(email)}>
            {busy ? '…' : 'Share'}
          </button>
        </div>

        {/* current access */}
        <label className="field-label" style={{ marginTop: 18 }}>People with access ({shares.length})</label>
        <div className="card" style={{ overflow: 'hidden', maxHeight: 180, overflowY: 'auto' }}>
          {shares.length === 0 ? (
            <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>Not shared with anyone yet.</div>
          ) : shares.map((s, i) => (
            <div key={s.user_id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 14px', borderTop: i ? '1px solid var(--border)' : 'none' }}>
              <span style={{ width: 32, height: 32, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--surface-3)', color: 'var(--text-soft)', fontSize: 12.5, fontWeight: 800 }}>{(s.name || s.email || '?')[0]?.toUpperCase()}</span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: 'block', fontSize: 14, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name || s.email}</span>
                <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.email}</span>
              </span>
              {s.role === 'technical'
                ? <AccessPicker value={s.permission} onChange={(p) => void setPerm(s, p)} />
                : <span title="Non-technical teammates can only view" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}><Icons.Eye size={13} />Can view</span>}
              <button type="button" className="focusable" title="Remove access" onClick={() => void remove(s)} style={{ width: 28, height: 28, borderRadius: 7, display: 'grid', placeItems: 'center', border: 'none', background: 'transparent', color: 'var(--text-faint)', cursor: 'pointer' }}><Icons.Close size={15} /></button>
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 20 }}>
          <button type="button" className="btn btn-outline" style={{ padding: '10px 18px' }} onClick={onClose}>Done</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
