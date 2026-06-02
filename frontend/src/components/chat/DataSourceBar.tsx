import { useEffect, useRef, useState } from 'react';
import type { SessionFileMeta } from '../../services/api';
import { Icons } from '../../icons';

export type DataSource =
  | { type: 'primary_db'; label: string; detail: string }
  | { type: 'file'; id: string; filename: string; mime_type: string; uploaded_at?: string | null };

/** Returns IDs to send to backend. DB → ['__primary_db__'], files → their UUIDs. */
export function getActiveFileIds(active: DataSource[]): string[] {
  return active.map((s) => (s.type === 'primary_db' ? '__primary_db__' : s.id));
}

function fileEmoji(mimeType: string): string {
  if (mimeType.includes('csv')) return '📄';
  if (mimeType.includes('excel') || mimeType.includes('spreadsheet') || mimeType.includes('xlsx')) return '📊';
  return '📄';
}

function formatUploadTime(isoString?: string | null): string {
  if (!isoString) return '';
  try {
    const d = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffH = Math.floor(diffMin / 60);
    if (diffH < 24) return `${diffH}h ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function triggerLabel(active: DataSource[]): string {
  if (active.length === 0) return 'Select data source';
  if (active.length === 1) {
    const s = active[0];
    return s.type === 'primary_db' ? `🗄️ ${s.detail}` : `${fileEmoji(s.mime_type)} ${s.filename}`;
  }
  const hasDb = active.some((s) => s.type === 'primary_db');
  const fileCount = active.filter((s) => s.type === 'file').length;
  if (hasDb && fileCount > 0) return `🗄️ DB + ${fileCount} file${fileCount > 1 ? 's' : ''}`;
  return `${active.length} files selected`;
}

type Props = {
  sources: DataSource[];
  active: DataSource[];
  onToggle: (source: DataSource) => void;
};

export default function DataSourceBar({ sources, active, onToggle }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handle = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [open]);

  if (sources.length === 0) return null;

  const isChecked = (src: DataSource) => {
    if (src.type === 'primary_db') return active.some((a) => a.type === 'primary_db');
    return active.some((a) => a.type === 'file' && a.id === src.id);
  };

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block', marginBottom: 12 }}>
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="chip focusable"
        style={{ maxWidth: 260, background: open ? 'var(--accent-soft)' : 'var(--surface)', borderColor: open ? 'var(--accent)' : 'var(--border)' }}
      >
        <span style={{ color: 'var(--text-faint)', fontSize: 12, flexShrink: 0 }}>Ask about:</span>
        <span style={{ fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{triggerLabel(active)}</span>
        {active.length > 1 && (
          <span style={{ fontSize: 10.5, fontWeight: 800, color: 'var(--on-accent)', background: 'var(--accent)', borderRadius: 99, padding: '1px 6px', flexShrink: 0 }}>{active.length}</span>
        )}
        <Icons.ChevronDown size={14} style={{ color: 'var(--text-faint)', flexShrink: 0, transition: 'transform .15s', transform: open ? 'rotate(180deg)' : 'none' }} />
      </button>

      {/* Dropdown — opens upward */}
      {open && (
        <div className="card pop-shadow scale-in" style={{ position: 'absolute', bottom: 'calc(100% + 8px)', left: 0, zIndex: 31, width: 320, maxWidth: '78vw', borderRadius: 'var(--r)', overflow: 'hidden', transformOrigin: 'bottom left' }}>
          <div style={{ padding: '12px 14px 10px', borderBottom: '1px solid var(--border)' }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.05em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 2 }}>Ask about</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Pick the database or one or more files.</div>
          </div>
          <div style={{ maxHeight: 280, overflowY: 'auto', padding: 6 }}>
            {sources.map((src) => {
              const checked = isChecked(src);
              const isDb = src.type === 'primary_db';
              const Icon = isDb ? Icons.Database : Icons.File;
              const label = isDb
                ? (src as Extract<DataSource, { type: 'primary_db' }>).label
                : (src as Extract<DataSource, { type: 'file' }>).filename;
              const sub = isDb
                ? (src as Extract<DataSource, { type: 'primary_db' }>).detail
                : formatUploadTime((src as Extract<DataSource, { type: 'file' }>).uploaded_at) || 'Excel file';
              return (
                <div
                  key={isDb ? '__db__' : src.id}
                  onClick={() => onToggle(src)}
                  className="focusable"
                  style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '9px 10px', borderRadius: 'var(--r-sm)', cursor: 'pointer', transition: 'background .12s', background: checked ? 'var(--accent-soft)' : 'transparent' }}
                  onMouseEnter={(e) => { if (!checked) e.currentTarget.style.background = 'var(--surface-2)'; }}
                  onMouseLeave={(e) => { if (!checked) e.currentTarget.style.background = 'transparent'; }}
                >
                  <span style={{ width: 18, height: 18, borderRadius: 5, flexShrink: 0, display: 'grid', placeItems: 'center', border: `2px solid ${checked ? 'var(--accent-strong)' : 'var(--border-strong)'}`, background: checked ? 'var(--accent-strong)' : 'transparent', color: 'var(--on-accent)' }}>
                    {checked && <Icons.Check size={12} />}
                  </span>
                  <span style={{ width: 30, height: 30, borderRadius: 8, flexShrink: 0, display: 'grid', placeItems: 'center', background: checked ? 'var(--accent)' : 'var(--surface-3)', color: checked ? 'var(--on-accent)' : 'var(--text-soft)' }}>
                    <Icon size={16} />
                  </span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: 'block', fontSize: 13.5, fontWeight: 600, color: checked ? 'var(--accent-ink)' : 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
                    <span style={{ display: 'block', fontSize: 11.5, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sub}</span>
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/** Build data sources list from session files + connected DB. */
export function buildDataSources(
  sessionFiles: SessionFileMeta[],
  connectedDbLabel: string | null,
): DataSource[] {
  const sources: DataSource[] = [];
  if (connectedDbLabel) {
    sources.push({ type: 'primary_db', label: 'Database', detail: connectedDbLabel });
  }
  for (const f of sessionFiles) {
    sources.push({ type: 'file', id: f.id, filename: f.filename, mime_type: f.mime_type, uploaded_at: f.uploaded_at ?? null });
  }
  return sources;
}
