import { useEffect, useState } from 'react';
import {
  createShare,
  listSentShares,
  resendShareEmail,
  revokeShare,
  revokeShareRecipient,
  type SentShare,
  type SharePermission,
  type ShareRecipientCreated,
} from '../../services/api';
import { Icons } from '../../icons';

type Props = {
  sessionId: string;
  open: boolean;
  onClose: () => void;
};

const PERMISSION_LABELS: Record<SharePermission, string> = {
  view_only: 'View only',
  read_data: 'Read data',
  edit_data: 'Edit data',
};

const PERMISSION_DESCRIPTIONS: Record<SharePermission, string> = {
  view_only: 'Recipient can read the chat history but cannot send messages.',
  read_data: 'Recipient can chat and run SELECT queries; no data or schema changes.',
  edit_data: 'Recipient has full access — read and modify data.',
};

type DraftRecipient = {
  email: string;
  permission: SharePermission;
};

function isValidEmail(s: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.trim());
}

export default function ShareSessionModal({ sessionId, open, onClose }: Props) {
  const [drafts, setDrafts] = useState<DraftRecipient[]>([
    { email: '', permission: 'read_data' },
  ]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<ShareRecipientCreated[] | null>(null);
  const [existing, setExisting] = useState<SentShare[]>([]);
  const [loadingExisting, setLoadingExisting] = useState(false);
  const [notifyEmail, setNotifyEmail] = useState(true);
  const [resendingId, setResendingId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setCreated(null);
    setDrafts([{ email: '', permission: 'read_data' }]);
    setNotifyEmail(true);
    void refreshExisting();
  }, [open, sessionId]);

  async function handleResendEmail(recipientId: string) {
    setResendingId(recipientId);
    try {
      await resendShareEmail(recipientId);
      await refreshExisting();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Failed to resend email');
      await refreshExisting();
    } finally {
      setResendingId(null);
    }
  }

  async function refreshExisting() {
    setLoadingExisting(true);
    try {
      const all = await listSentShares();
      setExisting(all.filter((s) => s.session_id === sessionId));
    } catch (e) {
      console.error('Failed to load existing shares:', e);
    } finally {
      setLoadingExisting(false);
    }
  }

  function updateDraft(idx: number, patch: Partial<DraftRecipient>) {
    setDrafts((prev) => prev.map((d, i) => (i === idx ? { ...d, ...patch } : d)));
  }

  function addRow() {
    setDrafts((prev) => [...prev, { email: '', permission: 'read_data' }]);
  }

  function removeRow(idx: number) {
    setDrafts((prev) => prev.filter((_, i) => i !== idx));
  }

  async function handleSubmit() {
    setError(null);
    const valid = drafts
      .map((d) => ({ ...d, email: d.email.trim().toLowerCase() }))
      .filter((d) => d.email);
    if (valid.length === 0) {
      setError('Add at least one recipient email.');
      return;
    }
    for (const r of valid) {
      if (!isValidEmail(r.email)) {
        setError(`Invalid email: ${r.email}`);
        return;
      }
    }
    const seen = new Set<string>();
    for (const r of valid) {
      if (seen.has(r.email)) {
        setError(`Duplicate email: ${r.email}`);
        return;
      }
      seen.add(r.email);
    }

    setSubmitting(true);
    try {
      const result = await createShare(sessionId, valid, { notifyViaEmail: notifyEmail });
      setCreated(result.recipients);
      await refreshExisting();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to share');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRevokeRecipient(recipientId: string) {
    if (!window.confirm('Revoke this recipient\'s access?')) return;
    try {
      await revokeShareRecipient(recipientId);
      await refreshExisting();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Failed to revoke');
    }
  }

  async function handleRevokeShare(shareId: string) {
    if (!window.confirm('Revoke this entire share (all recipients)?')) return;
    try {
      await revokeShare(shareId);
      await refreshExisting();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Failed to revoke');
    }
  }

  async function copyToClipboard(text: string) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      window.prompt('Copy this link:', text);
    }
  }

  if (!open) return null;

  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        className="card pop-shadow scale-in"
        style={{ width: '100%', maxWidth: 640, maxHeight: '90vh', overflowY: 'auto', borderRadius: 'var(--r-lg)', padding: 26 }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ width: 40, height: 40, borderRadius: 12, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}>
              <Icons.Share size={20} />
            </span>
            <h3 style={{ fontSize: 19, fontWeight: 700 }}>Share this chat</h3>
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

        {created ? (
          <div className="mb-6">
            <p className="text-sm text-green-700 mb-3 font-medium">
              Share link{created.length > 1 ? 's' : ''} created. Send {created.length > 1 ? 'each link' : 'this link'} to the matching recipient — only the addressee (logged in with that email) can accept it.
            </p>
            <ul className="space-y-2">
              {created.map((r) => (
                <li key={r.id} className="border border-gray-200 rounded p-3 bg-gray-50">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium text-gray-900">{r.email}</span>
                    <span className="text-xs text-gray-600 px-2 py-0.5 rounded bg-white border">
                      {PERMISSION_LABELS[r.permission]}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      readOnly
                      value={r.accept_url}
                      className="flex-1 px-2 py-1 border border-gray-300 rounded text-xs bg-white font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => copyToClipboard(r.accept_url)}
                      className="px-3 py-1 bg-indigo-600 text-white rounded text-xs hover:bg-indigo-700"
                    >
                      Copy
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={() => setCreated(null)}
                className="px-4 py-2 bg-gray-100 text-gray-700 rounded text-sm hover:bg-gray-200"
              >
                Share with more
              </button>
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 bg-indigo-600 text-white rounded text-sm hover:bg-indigo-700"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <>
            <label className="field-label">Invite by email</label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
              {drafts.map((d, idx) => (
                <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input
                    type="email"
                    value={d.email}
                    onChange={(e) => updateDraft(idx, { email: e.target.value })}
                    placeholder="colleague@pila.vn"
                    className="field focusable"
                    style={{ flex: 1 }}
                  />
                  <select
                    value={d.permission}
                    onChange={(e) => updateDraft(idx, { permission: e.target.value as SharePermission })}
                    className="field focusable"
                    style={{ width: 'auto' }}
                  >
                    <option value="view_only">View only</option>
                    <option value="read_data">Read data</option>
                    <option value="edit_data">Edit data</option>
                  </select>
                  {drafts.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeRow(idx)}
                      className="focusable"
                      style={{ width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', background: 'transparent', border: 'none' }}
                      aria-label="Remove"
                    >
                      <Icons.Close size={16} />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginBottom: 12 }}>
              {PERMISSION_DESCRIPTIONS[drafts[drafts.length - 1]?.permission ?? 'read_data']}
            </div>
            <button
              type="button"
              onClick={addRow}
              className="focusable"
              style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--accent-ink)', background: 'transparent', border: 'none', marginBottom: 16, padding: 0 }}
            >
              + Add another recipient
            </button>

            <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, fontSize: 13.5, color: 'var(--text-soft)', cursor: 'pointer', userSelect: 'none' }}>
              <input
                type="checkbox"
                checked={notifyEmail}
                onChange={(e) => setNotifyEmail(e.target.checked)}
                style={{ accentColor: 'var(--accent-strong)', width: 15, height: 15 }}
              />
              <span>Send email notification to recipients</span>
            </label>

            {error && (
              <div style={{ fontSize: 13, color: 'oklch(0.5 0.18 25)', background: 'oklch(0.95 0.05 25)', borderRadius: 'var(--r-sm)', padding: '8px 12px', marginBottom: 12 }}>
                {error}
              </div>
            )}

            <div style={{ display: 'flex', gap: 10, marginBottom: 24 }}>
              <button type="button" onClick={onClose} className="btn btn-outline" style={{ padding: '10px 18px' }} disabled={submitting}>Cancel</button>
              <button type="button" onClick={handleSubmit} disabled={submitting} className="btn btn-primary" style={{ flex: 1, padding: '10px 18px', opacity: submitting ? 0.7 : 1 }}>
                {submitting ? 'Sharing…' : 'Share'}
              </button>
            </div>
          </>
        )}

        {/* Existing shares for this session */}
        <div className="border-t border-gray-200 pt-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-2">
            Existing shares
            {loadingExisting && <span className="ml-2 text-gray-400">(loading…)</span>}
          </h4>
          {existing.length === 0 && !loadingExisting && (
            <p className="text-sm text-gray-500">No active shares for this chat.</p>
          )}
          <ul className="space-y-3">
            {existing.map((s) => (
              <li key={s.share_id} className="border border-gray-200 rounded p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-gray-500">
                    Shared {new Date(s.created_at).toLocaleString()}
                  </span>
                  {!s.revoked_at && (
                    <button
                      type="button"
                      onClick={() => handleRevokeShare(s.share_id)}
                      className="text-xs text-red-600 hover:text-red-800"
                    >
                      Revoke all
                    </button>
                  )}
                  {s.revoked_at && (
                    <span className="text-xs text-gray-400 italic">revoked</span>
                  )}
                </div>
                <ul className="space-y-1">
                  {s.recipients.map((r) => (
                    <li key={r.id} className="text-sm py-1">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0 flex-wrap">
                          <span className="truncate">{r.email}</span>
                          <span className="text-xs text-gray-500 px-1.5 py-0.5 rounded bg-gray-100">
                            {PERMISSION_LABELS[r.permission]}
                          </span>
                          {r.accepted_at ? (
                            <span className="text-xs text-green-700">accepted</span>
                          ) : (
                            <span className="text-xs text-amber-600">pending</span>
                          )}
                          {r.revoked_at && (
                            <span className="text-xs text-gray-400 italic">revoked</span>
                          )}
                        </div>
                        {!r.revoked_at && !s.revoked_at && (
                          <button
                            type="button"
                            onClick={() => handleRevokeRecipient(r.id)}
                            className="text-xs text-red-600 hover:text-red-800 ml-2 flex-shrink-0"
                          >
                            Revoke
                          </button>
                        )}
                      </div>
                      {/* Email status row — only relevant when share + recipient still active */}
                      {!r.revoked_at && !s.revoked_at && (
                        <div className="flex items-center gap-2 mt-1 ml-1 text-xs">
                          {r.email_sent_at ? (
                            <span className="text-green-700">
                              ✓ Email sent {new Date(r.email_sent_at).toLocaleString()}
                            </span>
                          ) : r.email_error ? (
                            <span
                              className="text-red-700 truncate max-w-[18rem]"
                              title={r.email_error}
                            >
                              ⚠ Email failed: {r.email_error}
                            </span>
                          ) : (
                            <span className="text-gray-400 italic">No email sent</span>
                          )}
                          <button
                            type="button"
                            onClick={() => handleResendEmail(r.id)}
                            disabled={resendingId === r.id}
                            className="text-indigo-600 hover:text-indigo-800 disabled:opacity-50"
                          >
                            {resendingId === r.id ? 'Sending…' : (r.email_sent_at ? 'Resend' : 'Send email')}
                          </button>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
