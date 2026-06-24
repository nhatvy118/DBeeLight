import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icons } from '../../icons';
import { toast } from '../Toaster';
import { listProjectShares, shareProject, unshareProject, type ProjectShare } from '../../services/api';

/** Technical owner shares a project's DATA (read-only) with an existing user by email. */
export default function ShareProjectModal({ project, onClose }: { project: { id: string; name: string }; onClose: () => void }) {
  const [shares, setShares] = useState<ProjectShare[]>([]);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try { setShares(await listProjectShares(project.id)); }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Failed to load access'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [project.id]);

  const add = async () => {
    if (!email.trim() || busy) return;
    setBusy(true);
    try {
      const s = await shareProject(project.id, email.trim());
      setShares((p) => [...p.filter((x) => x.user_id !== s.user_id), s]);
      setEmail('');
      toast.success(`Shared with ${s.email}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to share');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (s: ProjectShare) => {
    try { await unshareProject(project.id, s.user_id); setShares((p) => p.filter((x) => x.user_id !== s.user_id)); }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Failed to remove access'); }
  };

  return createPortal(
    <div className="backdrop" style={{ position: 'fixed', inset: 0, zIndex: 200, display: 'grid', placeItems: 'center', background: 'rgba(0,0,0,.4)', padding: 16 }} onClick={onClose}>
      <div className="card" style={{ width: 520, maxWidth: '100%', padding: 24, borderRadius: 'var(--r)' }} onClick={(e) => e.stopPropagation()}>
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
            Sharing gives people <strong>read-only</strong> access to this project's <strong>data</strong> — not your chats. They can ask questions and build charts, but never change anything.
          </span>
        </div>

        <label className="field-label">Share with a teammate by email</label>
        <div style={{ display: 'flex', gap: 8 }}>
          <input className="field focusable" placeholder="colleague@company.com" value={email} style={{ flex: 1 }}
            onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void add(); }} />
          <button type="button" className="btn btn-primary" style={{ padding: '12px 18px' }} disabled={!email.trim() || busy} onClick={() => void add()}>
            {busy ? '…' : 'Share'}
          </button>
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 6 }}>They must already have an account (an admin invites people in <strong>Admin → People</strong>).</p>

        <label className="field-label" style={{ marginTop: 20 }}>People with access</label>
        <div className="card" style={{ overflow: 'hidden' }}>
          {loading ? (
            <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>Loading…</div>
          ) : shares.length === 0 ? (
            <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>Not shared with anyone yet.</div>
          ) : shares.map((s, i) => (
            <div key={s.user_id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 14px', borderTop: i ? '1px solid var(--border)' : 'none' }}>
              <span style={{ width: 34, height: 34, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--surface-3)', color: 'var(--text-soft)', fontSize: 13, fontWeight: 800 }}>{(s.name || s.email || '?')[0]?.toUpperCase()}</span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: 'block', fontSize: 14, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name || s.email}</span>
                <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.email}</span>
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}><Icons.Eye size={13} />Can view</span>
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
