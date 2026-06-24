import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icons } from '../../icons';
import { toast } from '../Toaster';
import { getProjectConnection, type ExternalConnectionInfo } from '../../services/api';

/** A read-only "label : value" row with a copy button. */
function InfoRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      toast.error('Could not copy');
    }
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 14px', borderTop: '1px solid var(--border)' }}>
      <span style={{ width: 86, flexShrink: 0, fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '.04em' }}>{label}</span>
      <span style={{ flex: 1, minWidth: 0, fontSize: 14, fontFamily: 'var(--font-mono, ui-monospace, monospace)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {value || '—'}
      </span>
      <button type="button" className="focusable" title="Copy" onClick={() => void copy()} disabled={!value}
        style={{ width: 28, height: 28, flexShrink: 0, display: 'grid', placeItems: 'center', borderRadius: 7, border: 'none', background: 'transparent', color: copied ? 'var(--green-ink)' : 'var(--text-faint)', cursor: value ? 'pointer' : 'not-allowed' }}>
        {copied ? <Icons.Check size={15} /> : <Icons.Copy size={14} />}
      </button>
    </div>
  );
}

/** Owner-only modal showing an external project's stored connection details (host/port/db/user
 *  and the password behind a reveal toggle), so the owner can recover credentials they forgot. */
export default function ConnectionInfoModal({ project, onClose }: { project: { id: string; name: string }; onClose: () => void }) {
  const [info, setInfo] = useState<ExternalConnectionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const c = await getProjectConnection(project.id);
        if (!cancelled) setInfo(c);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load connection info');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [project.id]);

  return createPortal(
    <div className="backdrop" style={{ position: 'fixed', inset: 0, zIndex: 200, display: 'grid', placeItems: 'center', background: 'rgba(0,0,0,.4)', padding: 16 }} onClick={onClose}>
      <div className="card" style={{ width: 520, maxWidth: '100%', padding: 24, borderRadius: 'var(--r)' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <span style={{ width: 38, height: 38, borderRadius: 10, display: 'grid', placeItems: 'center', background: 'var(--green-soft)', color: 'var(--green-ink)' }}><Icons.Database size={19} /></span>
          <div style={{ minWidth: 0 }}>
            <h3 style={{ fontSize: 18, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>Connection info</h3>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{project.name}</p>
          </div>
        </div>

        {loading ? (
          <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>Loading…</div>
        ) : error ? (
          <div style={{ padding: 16, textAlign: 'center', color: 'var(--danger, #d93025)', fontSize: 13.5 }}>{error}</div>
        ) : info ? (
          <div className="card" style={{ overflow: 'hidden', borderRadius: 'var(--r-sm)' }}>
            {/* first row has no top border via a negative-margin trick: simplest is to keep border on all
                and accept the top one — but the card border already wraps, so start rows flush */}
            <div style={{ marginTop: -1 }}>
              <InfoRow label="Host" value={info.host} />
              <InfoRow label="Port" value={String(info.port)} />
              <InfoRow label="Database" value={info.database} />
              <InfoRow label="Username" value={info.username} />
              <InfoRow label="SSL" value={info.ssl ? 'required' : 'disabled'} />
            </div>
          </div>
        ) : null}

        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '11px 13px', background: 'var(--surface-2)', borderRadius: 'var(--r-sm)', marginTop: 14 }}>
          <Icons.Eye size={15} style={{ color: 'var(--text-muted)', flexShrink: 0, marginTop: 1 }} />
          <span style={{ fontSize: 12, lineHeight: 1.5, color: 'var(--text-soft)' }}>
            Only you (the owner) can see this. The password is hidden for security.
          </span>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 18 }}>
          <button type="button" className="btn btn-outline" style={{ padding: '10px 18px' }} onClick={onClose}>Done</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
