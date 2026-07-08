import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { getFilesQuota, type FileQuotaInfo } from '../../services/api';
import { Icons } from '../../icons';

type Props = {
  open: boolean;
  onClose: () => void;
};

function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return '—';
  if (n < 1024) return `${Math.round(n)} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/** Storage = hosted project databases only. Excel workbooks are ephemeral: the server
 *  deletes them after every editing turn and this device's browser keeps the only copy
 *  (IndexedDB) — they use no server storage at all. */
export default function StorageModal({ open, onClose }: Props) {
  const [quota, setQuota] = useState<FileQuotaInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setError(null);
    setLoading(true);
    getFilesQuota()
      .then((q) => {
        if (!cancelled) setQuota(q);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load storage');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  const used = quota?.used_bytes ?? 0;
  const limit = quota?.limit_bytes ?? 0; // real limit comes from the API — never hardcode
  const dbCount = quota?.file_count ?? 0;
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;

  return createPortal(
    <div
      className="backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="storage-modal-title"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="card pop-shadow scale-in"
        style={{ width: '100%', maxWidth: 560, display: 'flex', flexDirection: 'column', overflow: 'hidden', borderRadius: 'var(--r-lg)' }}
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

        <div className="px-5 py-4">
          {loading && (
            <p className="text-sm text-gray-500 dark:text-gray-400">Loading…</p>
          )}
          {error && !loading && (
            <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
          )}
          {!loading && !error && quota && (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-gray-500 dark:text-gray-400">
                This measures the databases DBeeLight hosts for your projects (limit{' '}
                <span className="font-medium text-gray-700 dark:text-gray-300">{formatBytes(limit)}</span>).
                Projects connected to your own external database are not counted.
              </p>
              <div>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="text-gray-700 dark:text-gray-200 font-medium">
                    {formatBytes(used)} used
                  </span>
                  <span className="text-gray-500 dark:text-gray-400">
                    of {formatBytes(limit)}{dbCount > 0 ? ` · ${dbCount} hosted database${dbCount > 1 ? 's' : ''}` : ''}
                  </span>
                </div>
                <div style={{ height: 9, borderRadius: 99, background: 'var(--surface-3)', overflow: 'hidden' }}>
                  <div
                    style={{
                      height: '100%', width: `${pct}%`, borderRadius: 99,
                      background: pct >= 95 ? 'oklch(0.6 0.18 25)' : pct >= 80 ? 'oklch(0.75 0.15 70)' : 'linear-gradient(90deg, var(--accent-strong), var(--accent))',
                    }}
                  />
                </div>
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Excel workbooks you edit in chat are kept on your device, not on our servers —
                they never count against this limit. To free up space, delete tables or projects
                you no longer need.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
