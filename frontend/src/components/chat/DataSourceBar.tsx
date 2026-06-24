import { useEffect, useRef, useState } from 'react';
import type { SessionFileMeta } from '../../services/api';
import { Icons } from '../../icons';
import { FileTypeBadge, getFileTypeInfo } from '../../utils/fileType';

/** A pickable data source. Only uploaded files are pickable — the database is the
 * implicit default when nothing is selected (see getActiveFileIds). */
export type DataSource = {
  type: 'file';
  id: string;
  filename: string;
  mime_type: string;
  uploaded_at?: string | null;
  /** "query" = Q&A table (SQL); "workbook" = Excel-edit file. Drives the source badge. */
  kind?: 'query' | 'workbook';
};

/** File UUIDs to scope this turn to. Empty selection → the caller falls back to the
 * primary DB (sends ['__primary_db__']); i.e. "no file picked = ask the database". */
export function getActiveFileIds(active: DataSource[]): string[] {
  return active.map((s) => s.id);
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

function triggerLabel(active: DataSource[], dbLabel: string | null): string {
  // Nothing picked → the database is the default target (when one is connected);
  // with no database, the user must pick a file.
  if (active.length === 0) return dbLabel ? `Asking: ${dbLabel}` : 'Select a file';
  if (active.length === 1) {
    const s = active[0];
    return `${getFileTypeInfo(s.filename, s.mime_type).emoji} ${s.filename}`;
  }
  return `${active.length} files selected`;
}

type Props = {
  sources: DataSource[];
  active: DataSource[];
  onToggle: (source: DataSource) => void;
  /** Label of the primary DB, shown as the default target when no file is picked. */
  dbLabel: string | null;
};

export default function DataSourceBar({ sources, active, onToggle, dbLabel }: Props) {
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

  const isChecked = (src: DataSource) => active.some((a) => a.id === src.id);

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block', marginBottom: 12 }}>
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="chip focusable"
        style={{ maxWidth: 260, background: open ? 'var(--accent-soft)' : 'var(--surface)', borderColor: open ? 'var(--accent)' : 'var(--border)' }}
      >
        <span style={{ color: 'var(--text-faint)', fontSize: 12, flexShrink: 0 }}>Source:</span>
        <span style={{ fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{triggerLabel(active, dbLabel)}</span>
        {active.length > 1 && (
          <span style={{ fontSize: 10.5, fontWeight: 800, color: 'var(--on-accent)', background: 'var(--accent)', borderRadius: 99, padding: '1px 6px', flexShrink: 0 }}>{active.length}</span>
        )}
        <Icons.ChevronDown size={14} style={{ color: 'var(--text-faint)', flexShrink: 0, transition: 'transform .15s', transform: open ? 'rotate(180deg)' : 'none' }} />
      </button>

      {/* Dropdown — opens upward */}
      {open && (
        <div className="card pop-shadow scale-in" style={{ position: 'absolute', bottom: 'calc(100% + 8px)', left: 0, zIndex: 31, width: 320, maxWidth: '78vw', borderRadius: 'var(--r)', overflow: 'hidden', transformOrigin: 'bottom left' }}>
          <div style={{ padding: '12px 14px 10px', borderBottom: '1px solid var(--border)' }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.05em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 2 }}>Files in this chat</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {dbLabel
                ? <>Leave empty to ask <b>{dbLabel}</b>. Pick a <b>Q&amp;A</b> file to query it, or an <b>Excel</b> file to edit it.</>
                : <>Pick a <b>Q&amp;A</b> file to query, or an <b>Excel</b> file to edit.</>}
            </div>
          </div>
          <div style={{ maxHeight: 300, overflowY: 'auto', padding: 6 }}>
            {(() => {
              // Two purposes, shown as separate groups so it's clear which file does what.
              const queryFiles = sources.filter((s) => s.kind !== 'workbook');
              const editFiles = sources.filter((s) => s.kind === 'workbook');
              const renderRow = (src: DataSource) => {
                const checked = isChecked(src);
                const sub = formatUploadTime(src.uploaded_at) || `${getFileTypeInfo(src.filename, src.mime_type).label} file`;
                return (
                  <div
                    key={src.id}
                    onClick={() => onToggle(src)}
                    className="focusable"
                    style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '9px 10px', borderRadius: 'var(--r-sm)', cursor: 'pointer', transition: 'background .12s', background: checked ? 'var(--accent-soft)' : 'transparent' }}
                    onMouseEnter={(e) => { if (!checked) e.currentTarget.style.background = 'var(--surface-2)'; }}
                    onMouseLeave={(e) => { if (!checked) e.currentTarget.style.background = 'transparent'; }}
                  >
                    <span style={{ width: 18, height: 18, borderRadius: 5, flexShrink: 0, display: 'grid', placeItems: 'center', border: `2px solid ${checked ? 'var(--accent-strong)' : 'var(--border-strong)'}`, background: checked ? 'var(--accent-strong)' : 'transparent', color: 'var(--on-accent)' }}>
                      {checked && <Icons.Check size={12} />}
                    </span>
                    <FileTypeBadge filename={src.filename} mimeType={src.mime_type} size={30} radius={8} />
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ display: 'block', fontSize: 13.5, fontWeight: 600, color: checked ? 'var(--accent-ink)' : 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{src.filename}</span>
                      <span style={{ display: 'block', fontSize: 11.5, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sub}</span>
                    </span>
                  </div>
                );
              };
              const header = (text: string, tone: 'green' | 'accent') => (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px 4px', fontSize: 10.5, fontWeight: 800, letterSpacing: '.06em', textTransform: 'uppercase', color: tone === 'green' ? 'var(--green-ink)' : 'var(--accent-ink)' }}>
                  {text}
                </div>
              );
              return (
                <>
                  {queryFiles.length > 0 && header('Q&A — query', 'green')}
                  {queryFiles.map(renderRow)}
                  {editFiles.length > 0 && header('Excel — edit', 'accent')}
                  {editFiles.map(renderRow)}
                </>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
}

/** Build the pickable file list from the session's uploaded files. */
export function buildDataSources(sessionFiles: SessionFileMeta[]): DataSource[] {
  return sessionFiles.map((f) => ({
    type: 'file',
    id: f.id,
    filename: f.filename,
    mime_type: f.mime_type,
    uploaded_at: f.uploaded_at ?? null,
    kind: f.kind,
  }));
}
