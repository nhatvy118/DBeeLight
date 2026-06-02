import { useEffect, useState } from 'react';
import {
  deleteSessionFile,
  downloadStoredSessionFile,
  getFilesQuota,
  listExportFilesInventory,
  listUserFilesInventory,
  type ExportFileInventoryRow,
  type FileQuotaInfo,
  type UserFileInventoryRow,
} from '../../services/api';
import { Icons } from '../../icons';

type Props = {
  open: boolean;
  onClose: () => void;
};

type TabId = 'import' | 'export';

function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return '—';
  if (n < 1024) return `${Math.round(n)} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function sortInventory<T extends { uploaded_at?: string | null }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const ta = a.uploaded_at ? Date.parse(a.uploaded_at) : 0;
    const tb = b.uploaded_at ? Date.parse(b.uploaded_at) : 0;
    return tb - ta;
  });
}

export default function StorageModal({ open, onClose }: Props) {
  const [tab, setTab] = useState<TabId>('import');
  const [quota, setQuota] = useState<FileQuotaInfo | null>(null);
  const [files, setFiles] = useState<UserFileInventoryRow[]>([]);
  const [exportFiles, setExportFiles] = useState<ExportFileInventoryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deletingExportId, setDeletingExportId] = useState<string | null>(null);
  const [downloadingExportId, setDownloadingExportId] = useState<string | null>(null);

  async function refreshAll() {
    const [q, inv, exp] = await Promise.all([
      getFilesQuota(),
      listUserFilesInventory(),
      listExportFilesInventory(),
    ]);
    setQuota(q);
    setFiles(sortInventory(inv));
    setExportFiles(sortInventory(exp));
  }

  useEffect(() => {
    if (open) setTab('import');
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setError(null);
    setLoading(true);
    (async () => {
      try {
        const [q, inv, exp] = await Promise.all([
          getFilesQuota(),
          listUserFilesInventory(),
          listExportFilesInventory(),
        ]);
        if (cancelled) return;
        setQuota(q);
        setFiles(sortInventory(inv));
        setExportFiles(sortInventory(exp));
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load storage');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  async function handleDeleteImport(file: UserFileInventoryRow) {
    if (
      !window.confirm(
        `Remove “${file.filename}” from storage? This frees quota and removes it from the chat session.`,
      )
    ) {
      return;
    }
    setDeletingId(file.id);
    setError(null);
    try {
      await deleteSessionFile(file.id);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete file');
    } finally {
      setDeletingId(null);
    }
  }

  async function handleDownloadExport(row: ExportFileInventoryRow) {
    if (downloadingExportId) return;
    setDownloadingExportId(row.id);
    setError(null);
    try {
      await downloadStoredSessionFile(row.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Download failed');
    } finally {
      setDownloadingExportId(null);
    }
  }

  async function handleDeleteExport(row: ExportFileInventoryRow) {
    if (
      !window.confirm(
        `Remove “${row.filename}” (chat export)? This frees quota and removes download links in that session.`,
      )
    ) {
      return;
    }
    setDeletingExportId(row.id);
    setError(null);
    try {
      await deleteSessionFile(row.id);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete file');
    } finally {
      setDeletingExportId(null);
    }
  }

  if (!open) return null;

  const used = quota?.used_bytes ?? 0;
  const limit = quota?.limit_bytes ?? 5 * 1024 * 1024 * 1024;
  const imp = quota?.import_used_bytes ?? 0;
  const exp = quota?.export_used_bytes ?? 0;
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;

  return (
    <div
      className="backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="storage-modal-title"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="card pop-shadow scale-in"
        style={{ width: '100%', maxWidth: 560, height: 'min(50rem, 85vh)', display: 'flex', flexDirection: 'column', overflow: 'hidden', borderRadius: 'var(--r-lg)' }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ width: 40, height: 40, borderRadius: 12, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}>
              <Icons.HardDrive size={20} />
            </span>
            <h3 id="storage-modal-title" style={{ fontSize: 19, fontWeight: 700 }}>Storage</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="focusable"
            style={{ width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', background: 'transparent', border: 'none' }}
            aria-label="Close"
          >
            <Icons.Close size={18} />
          </button>
        </div>

        <div style={{ padding: '12px 24px 0', borderBottom: '1px solid var(--border)' }}>
          <div className="seg" style={{ marginBottom: 12 }}>
            <button type="button" data-on={tab === 'import'} onClick={() => setTab('import')}>Import</button>
            <button type="button" data-on={tab === 'export'} onClick={() => setTab('export')}>Export</button>
          </div>
        </div>

        <div className="px-5 py-4 flex flex-col flex-1 min-h-0 overflow-hidden">
          {loading && (
            <div className="flex flex-1 min-h-0 items-center justify-center">
              <p className="text-sm text-gray-500 dark:text-gray-400">Loading…</p>
            </div>
          )}
          {error && !loading && (
            <div className="flex flex-1 min-h-0 items-center justify-center px-2">
              <p className="text-sm text-red-600 dark:text-red-400 text-center">{error}</p>
            </div>
          )}
          {!loading && !error && quota && (
            <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-2 shrink-0">
                Import and Export (under{' '}
                <code className="text-[10px]">file_handle/…/import|export</code>) share a{' '}
                <span className="font-medium text-gray-700 dark:text-gray-300">5 GB</span> limit.
                Excel MCP staging uses{' '}
                <code className="text-[10px]">file_handle/…/excel_mcp</code> and is not counted here.
              </p>
              <div className="mb-1 flex justify-between text-sm shrink-0">
                <span className="text-gray-700 dark:text-gray-200 font-medium">
                  {formatBytes(used)} used
                </span>
                <span className="text-gray-500 dark:text-gray-400">
                  of {formatBytes(limit)}
                </span>
              </div>
              <div className="shrink-0 mb-2" style={{ height: 9, borderRadius: 99, background: 'var(--surface-3)', overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%', width: `${pct}%`, borderRadius: 99,
                    background: pct >= 95 ? 'oklch(0.6 0.18 25)' : pct >= 80 ? 'oklch(0.75 0.15 70)' : 'linear-gradient(90deg, var(--accent-strong), var(--accent))',
                  }}
                />
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-3 shrink-0">
                Import {formatBytes(imp)} · Export {formatBytes(exp)}
              </p>

              <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
                {tab === 'import' && (
                  <>
                    <div className="shrink-0 mb-2 flex min-h-[4.5rem] flex-col gap-2">
                      <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                        Indexed session files ({files.length})
                      </h4>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        Files attached in chat (RAG / SQLite).
                      </p>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto pr-1">
                      {files.length === 0 ? (
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          No files yet. Attach a file in chat to index it here.
                        </p>
                      ) : (
                        <ul style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                          {files.map((f) => (
                            <li
                              key={f.id}
                              style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 14px', borderRadius: 'var(--r-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
                            >
                              <span style={{ width: 36, height: 36, borderRadius: 9, display: 'grid', placeItems: 'center', background: 'var(--green-soft)', color: 'var(--green-ink)', flexShrink: 0 }}>
                                <Icons.Table size={18} />
                              </span>
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontWeight: 600, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {f.filename}
                                </div>
                                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                                  <span className="tabular">{formatBytes(f.size_bytes)}</span>
                                  {' · '}
                                  <span style={{ fontFamily: 'var(--font-mono)' }}>Session {f.session_id}</span>
                                </div>
                              </div>
                              <button
                                type="button"
                                onClick={() => void handleDeleteImport(f)}
                                disabled={deletingId === f.id}
                                className="focusable"
                                aria-label={`Delete ${f.filename}`}
                                title="Remove file from storage"
                                style={{ width: 32, height: 32, borderRadius: 8, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', background: 'transparent', border: 'none', flexShrink: 0, opacity: deletingId === f.id ? 0.4 : 1 }}
                                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; e.currentTarget.style.color = 'oklch(0.6 0.18 25)'; }}
                                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-muted)'; }}
                              >
                                <Icons.Trash size={16} />
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </>
                )}

                {tab === 'export' && (
                  <>
                    <div className="shrink-0 mb-2 flex min-h-[4.5rem] flex-col gap-2">
                      <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                        Chat exports ({exportFiles.length})
                      </h4>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        Excel files the assistant produced in chat (download chips). Deleting removes the
                        file and its search index for that session.
                      </p>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto pr-1">
                      {exportFiles.length === 0 ? (
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          No chat exports yet. Export a table in chat to see it here.
                        </p>
                      ) : (
                        <ul style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                          {exportFiles.map((f) => (
                            <li
                              key={f.id}
                              style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 14px', borderRadius: 'var(--r-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
                            >
                              <span style={{ width: 36, height: 36, borderRadius: 9, display: 'grid', placeItems: 'center', background: 'var(--green-soft)', color: 'var(--green-ink)', flexShrink: 0 }}>
                                <Icons.Table size={18} />
                              </span>
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontWeight: 600, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {f.filename}
                                </div>
                                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                                  <span className="tabular">{formatBytes(f.size_bytes)}</span>
                                  {' · '}
                                  <span style={{ fontFamily: 'var(--font-mono)' }}>Session {f.session_id}</span>
                                </div>
                              </div>
                              <button
                                type="button"
                                onClick={() => void handleDownloadExport(f)}
                                disabled={
                                  downloadingExportId === f.id ||
                                  deletingExportId === f.id ||
                                  Boolean(downloadingExportId && downloadingExportId !== f.id)
                                }
                                className="focusable"
                                aria-label={`Download ${f.filename}`}
                                title="Download"
                                style={{ width: 32, height: 32, borderRadius: 8, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', background: 'transparent', border: 'none', flexShrink: 0, opacity: (downloadingExportId === f.id || deletingExportId === f.id || Boolean(downloadingExportId && downloadingExportId !== f.id)) ? 0.4 : 1 }}
                                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; e.currentTarget.style.color = 'var(--accent-ink)'; }}
                                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-muted)'; }}
                              >
                                {downloadingExportId === f.id ? <span style={{ fontSize: 12, fontWeight: 600 }}>…</span> : <Icons.Download size={16} />}
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleDeleteExport(f)}
                                disabled={deletingExportId === f.id || Boolean(downloadingExportId)}
                                className="focusable"
                                aria-label={`Delete ${f.filename}`}
                                title="Remove export from storage"
                                style={{ width: 32, height: 32, borderRadius: 8, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', background: 'transparent', border: 'none', flexShrink: 0, opacity: (deletingExportId === f.id || Boolean(downloadingExportId)) ? 0.4 : 1 }}
                                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; e.currentTarget.style.color = 'oklch(0.6 0.18 25)'; }}
                                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-muted)'; }}
                              >
                                <Icons.Trash size={16} />
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
