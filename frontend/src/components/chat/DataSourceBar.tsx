import { useEffect, useRef, useState } from 'react';
import type { SessionFileMeta } from '../../services/api';

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
    <div ref={ref} className="relative mb-3 inline-block">
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm text-gray-700 dark:text-gray-200 hover:border-indigo-400 dark:hover:border-indigo-500 transition-colors shadow-sm"
      >
        <span className="text-xs text-gray-400 dark:text-gray-500 shrink-0">Query on:</span>
        <span className="font-medium max-w-[220px] truncate">{triggerLabel(active)}</span>
        {active.length > 0 && (
          <span className="shrink-0 inline-flex items-center justify-center w-4 h-4 rounded-full bg-indigo-100 dark:bg-indigo-900 text-indigo-600 dark:text-indigo-300 text-[10px] font-bold">
            {active.length}
          </span>
        )}
        <svg
          className={`w-3.5 h-3.5 text-gray-400 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
          viewBox="0 0 20 20" fill="currentColor"
        >
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </button>

      {/* Dropdown — opens upward, fixed height, scrollable after 4 items */}
      {open && (
        <div className="absolute bottom-full mb-1.5 left-0 z-50 w-72 rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-lg overflow-y-auto max-h-[232px]">
          {sources.map((src, i) => {
            const checked = isChecked(src);
            const isDb = src.type === 'primary_db';

            return (
              <button
                key={isDb ? '__db__' : src.id}
                type="button"
                onClick={() => onToggle(src)}
                className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
                  i > 0 ? 'border-t border-gray-100 dark:border-slate-700' : ''
                } ${checked ? 'bg-indigo-50 dark:bg-indigo-900/30' : 'hover:bg-gray-50 dark:hover:bg-slate-700'}`}
              >
                {/* Checkbox */}
                <div className={`shrink-0 w-4 h-4 rounded border-2 flex items-center justify-center transition-colors ${
                  checked
                    ? 'bg-indigo-600 border-indigo-600 dark:bg-indigo-500 dark:border-indigo-500'
                    : 'border-gray-300 dark:border-slate-500 bg-white dark:bg-slate-700'
                }`}>
                  {checked && (
                    <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 12 12" fill="none">
                      <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </div>

                {/* Icon */}
                <span className="text-base shrink-0">{isDb ? '🗄️' : fileEmoji((src as Extract<DataSource, {type:'file'}>).mime_type)}</span>

                {/* Text */}
                <div className="min-w-0 flex-1">
                  <div className={`text-sm font-semibold truncate ${checked ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-800 dark:text-gray-100'}`}>
                    {isDb ? (src as Extract<DataSource, {type:'primary_db'}>).label : (src as Extract<DataSource, {type:'file'}>).filename}
                  </div>
                  <div className="text-xs text-gray-400 dark:text-gray-500 truncate">
                    {isDb
                      ? (src as Extract<DataSource, {type:'primary_db'}>).detail
                      : formatUploadTime((src as Extract<DataSource, {type:'file'}>).uploaded_at)}
                  </div>
                </div>
              </button>
            );
          })}
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
