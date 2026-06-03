import { useEffect, useReducer } from 'react';
import { createPortal } from 'react-dom';
import { Icons, type IconComponent } from '../icons';

export type ToastType = 'error' | 'success' | 'info' | 'warning';

type Toast = { id: number; type: ToastType; message: string };

const DURATION: Record<ToastType, number> = {
  error: 6000,
  warning: 5000,
  success: 4000,
  info: 4000,
};

// Module-level pub/sub store so `toast.error(...)` works from anywhere
// (components, async handlers, non-hook code) — like react-hot-toast.
let store: Toast[] = [];
let listeners: Array<() => void> = [];
let nextId = 1;

function emit() {
  for (const l of listeners) l();
}

function dismiss(id: number) {
  store = store.filter((t) => t.id !== id);
  emit();
}

function push(type: ToastType, message: string) {
  const id = nextId++;
  // De-dupe back-to-back identical messages (e.g. repeated failed clicks).
  if (store.some((t) => t.type === type && t.message === message)) return id;
  store = [...store, { id, type, message }];
  emit();
  if (DURATION[type]) {
    setTimeout(() => dismiss(id), DURATION[type]);
  }
  return id;
}

export const toast = {
  error: (message: string) => push('error', message),
  success: (message: string) => push('success', message),
  info: (message: string) => push('info', message),
  warning: (message: string) => push('warning', message),
  dismiss,
};

const STYLE: Record<ToastType, { icon: IconComponent; color: string; soft: string; ink: string }> = {
  error: { icon: Icons.Alert, color: 'var(--danger)', soft: 'var(--danger-soft)', ink: 'var(--danger-ink)' },
  warning: { icon: Icons.Alert, color: 'var(--accent)', soft: 'var(--accent-soft)', ink: 'var(--accent-ink)' },
  success: { icon: Icons.Check, color: 'var(--green, #2e9e5b)', soft: 'var(--green-soft, #e6f4ea)', ink: 'var(--green-ink, #1a7f37)' },
  info: { icon: Icons.Info, color: 'var(--accent)', soft: 'var(--accent-soft)', ink: 'var(--accent-ink)' },
};

function ToastItem({ t }: { t: Toast }) {
  const s = STYLE[t.type];
  return (
    <div
      className="card pop-shadow"
      role={t.type === 'error' ? 'alert' : 'status'}
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 11,
        padding: '12px 12px 12px 14px', width: 340, maxWidth: '92vw',
        borderRadius: 'var(--r)', borderLeft: `3px solid ${s.color}`,
        animation: 'toastIn .22s cubic-bezier(.2,.8,.2,1) both',
      }}
    >
      <span style={{ width: 30, height: 30, borderRadius: 8, flexShrink: 0, display: 'grid', placeItems: 'center', background: s.soft, color: s.ink }}>
        <s.icon size={17} />
      </span>
      <span style={{ flex: 1, minWidth: 0, fontSize: 13.5, lineHeight: 1.45, color: 'var(--text)', wordBreak: 'break-word', paddingTop: 4 }}>
        {t.message}
      </span>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => dismiss(t.id)}
        className="focusable"
        style={{ width: 26, height: 26, flexShrink: 0, display: 'grid', placeItems: 'center', borderRadius: 6, border: 'none', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer' }}
      >
        <Icons.Close size={15} />
      </button>
    </div>
  );
}

/** Mount once near the app root. Renders the toast stack (top-right) via a portal. */
export function Toaster() {
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    listeners.push(force);
    return () => { listeners = listeners.filter((l) => l !== force); };
  }, []);

  if (store.length === 0) return null;
  return createPortal(
    <div style={{ position: 'fixed', top: 16, right: 16, zIndex: 2000, display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-end', pointerEvents: 'none' }}>
      {store.map((t) => (
        <div key={t.id} style={{ pointerEvents: 'auto' }}>
          <ToastItem t={t} />
        </div>
      ))}
    </div>,
    document.body,
  );
}
