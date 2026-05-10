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
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="storage-modal-title"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-slate-900 rounded-xl shadow-xl border border-gray-200 dark:border-slate-700 max-w-xl w-full h-[min(50rem,85vh)] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 dark:border-slate-800">
          <h3 id="storage-modal-title" className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Storage
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 text-2xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="px-5 pt-3 border-b border-gray-100 dark:border-slate-800 flex gap-1">
          <button
            type="button"
            onClick={() => setTab('import')}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
              tab === 'import'
                ? 'bg-gray-100 dark:bg-slate-800 text-gray-900 dark:text-gray-100'
                : 'text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'
            }`}
          >
            Import
          </button>
          <button
            type="button"
            onClick={() => setTab('export')}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
              tab === 'export'
                ? 'bg-gray-100 dark:bg-slate-800 text-gray-900 dark:text-gray-100'
                : 'text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'
            }`}
          >
            Export
          </button>
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
              <div className="h-2 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden mb-2 shrink-0">
                <div
                  className={`h-full rounded-full transition-all ${
                    pct >= 95
                      ? 'bg-red-500'
                      : pct >= 80
                        ? 'bg-amber-500'
                        : 'bg-indigo-600 dark:bg-indigo-500'
                  }`}
                  style={{ width: `${pct}%` }}
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
                        <ul className="space-y-2">
                          {files.map((f) => (
                            <li
                              key={f.id}
                              className="flex items-center gap-2 text-sm rounded-lg border border-gray-100 dark:border-slate-800 px-3 py-2 bg-gray-50/80 dark:bg-slate-800/50"
                            >
                              <div className="min-w-0 flex-1">
                                <div className="text-gray-900 dark:text-gray-100 break-all font-medium">
                                  {f.filename}
                                </div>
                                <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 font-mono">
                                  Session: {f.session_id}
                                </div>
                              </div>
                              <span className="text-gray-500 dark:text-gray-400 shrink-0 tabular-nums text-xs sm:text-sm">
                                {formatBytes(f.size_bytes)}
                              </span>
                              <button
                                type="button"
                                onClick={() => void handleDeleteImport(f)}
                                disabled={deletingId === f.id}
                                className="shrink-0 flex h-8 w-8 items-center justify-center rounded-lg text-lg leading-none text-gray-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/50 dark:hover:text-red-400 disabled:opacity-40"
                                aria-label={`Delete ${f.filename}`}
                                title="Remove file from storage"
                              >
                                ×
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
                        <ul className="space-y-2">
                          {exportFiles.map((f) => (
                            <li
                              key={f.id}
                              className="flex items-center gap-2 text-sm rounded-lg border border-gray-100 dark:border-slate-800 px-3 py-2 bg-gray-50/80 dark:bg-slate-800/50"
                            >
                              <div className="min-w-0 flex-1">
                                <div className="text-gray-900 dark:text-gray-100 break-all font-medium">
                                  {f.filename}
                                </div>
                                <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 font-mono">
                                  Session: {f.session_id}
                                </div>
                              </div>
                              <span className="text-gray-500 dark:text-gray-400 shrink-0 tabular-nums text-xs sm:text-sm">
                                {formatBytes(f.size_bytes)}
                              </span>
                              <button
                                type="button"
                                onClick={() => void handleDownloadExport(f)}
                                disabled={
                                  downloadingExportId === f.id ||
                                  deletingExportId === f.id ||
                                  Boolean(downloadingExportId && downloadingExportId !== f.id)
                                }
                                className="shrink-0 flex h-8 w-8 items-center justify-center rounded-lg text-gray-500 hover:bg-indigo-50 hover:text-indigo-700 dark:text-gray-400 dark:hover:bg-indigo-950/40 dark:hover:text-indigo-300 disabled:opacity-40"
                                aria-label={`Download ${f.filename}`}
                                title="Download"
                              >
                                {downloadingExportId === f.id ? (
                                  <span className="text-xs font-medium">…</span>
                                ) : (
                                  <svg
                                    className="w-4 h-4"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="2"
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    aria-hidden
                                  >
                                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                    <polyline points="7 10 12 15 17 10" />
                                    <line x1="12" y1="15" x2="12" y2="3" />
                                  </svg>
                                )}
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleDeleteExport(f)}
                                disabled={deletingExportId === f.id || Boolean(downloadingExportId)}
                                className="shrink-0 flex h-8 w-8 items-center justify-center rounded-lg text-lg leading-none text-gray-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/50 dark:hover:text-red-400 disabled:opacity-40"
                                aria-label={`Delete ${f.filename}`}
                                title="Remove export from storage"
                              >
                                ×
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
