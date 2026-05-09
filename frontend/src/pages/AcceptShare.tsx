import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  acceptShare,
  previewShare,
  type SharePermission,
  type SharePreview,
} from '../services/api';

type Props = {
  token: string;
};

const PERMISSION_LABELS: Record<SharePermission, string> = {
  view_only: 'View only',
  read_data: 'Read data (SELECT only)',
  edit_data: 'Edit data (full access)',
};

export default function AcceptShare({ token }: Props) {
  const { user, isLoading: authLoading } = useAuth();
  const [preview, setPreview] = useState<SharePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const p = await previewShare(token);
        if (!cancelled) setPreview(p);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load share');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  function handleLogin() {
    const next = `/share/accept/${encodeURIComponent(token)}`;
    window.location.href = `/api/auth/google/login?next=${encodeURIComponent(next)}`;
  }

  async function handleAccept() {
    setError(null);
    setAccepting(true);
    try {
      const result = await acceptShare(token);
      // Navigate to the forked session.
      const target = `/chat/${result.project_id}/${result.session_id}`;
      window.history.pushState({}, '', target);
      window.dispatchEvent(new PopStateEvent('popstate'));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to accept share');
      setAccepting(false);
    }
  }

  if (loading || authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-500">Loading shared chat…</p>
      </div>
    );
  }

  if (error && !preview) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="max-w-md bg-white rounded-lg border border-red-200 shadow p-6">
          <h1 className="text-xl font-semibold text-red-700 mb-2">Cannot open share</h1>
          <p className="text-sm text-gray-700">{error}</p>
        </div>
      </div>
    );
  }

  if (!preview) return null;

  const needsLogin = !user || !preview.logged_in;
  const wrongAccount = !needsLogin && !preview.email_match;

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-md w-full bg-white rounded-lg border border-gray-200 shadow p-6">
        <h1 className="text-xl font-semibold text-gray-900 mb-2">
          {preview.session_name ? `Shared chat: ${preview.session_name}` : 'Shared chat'}
        </h1>
        <p className="text-sm text-gray-600 mb-1">
          Sent to <span className="font-medium">{preview.recipient_email}</span>
        </p>
        <p className="text-sm text-gray-600 mb-4">
          Access level: <span className="font-medium">{PERMISSION_LABELS[preview.permission]}</span>
        </p>

        {needsLogin && (
          <>
            <p className="text-sm text-gray-700 mb-4">
              You must sign in with the email above to access this shared chat.
            </p>
            <button
              type="button"
              onClick={handleLogin}
              className="w-full px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700"
            >
              Sign in with Google
            </button>
          </>
        )}

        {wrongAccount && user && (
          <>
            <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
              You are signed in as <strong>{user.email}</strong>, but this share was sent to <strong>{preview.recipient_email}</strong>. Sign out and sign in with the correct account.
            </p>
            <button
              type="button"
              onClick={async () => {
                await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
                handleLogin();
              }}
              className="w-full px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700"
            >
              Switch account
            </button>
          </>
        )}

        {!needsLogin && !wrongAccount && (
          <>
            {preview.accepted_at ? (
              <p className="text-sm text-gray-700 mb-4">
                You already accepted this share. Open it again to continue chatting.
              </p>
            ) : (
              <p className="text-sm text-gray-700 mb-4">
                Accepting will create your own copy of the chat history. Your messages from there on will be private to you.
              </p>
            )}
            {error && (
              <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2 mb-3">
                {error}
              </div>
            )}
            <button
              type="button"
              onClick={handleAccept}
              disabled={accepting}
              className="w-full px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
            >
              {accepting
                ? 'Opening…'
                : preview.accepted_at
                ? 'Open shared chat'
                : 'Accept and open chat'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
