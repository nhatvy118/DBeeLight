import { useEffect, useReducer } from 'react';
import Modal from './modals/Modal';
import { Icons } from '../icons';

type ConfirmOpts = {
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Destructive action → red tone + red confirm button. */
  danger?: boolean;
};

type Pending = ConfirmOpts & { resolve: (v: boolean) => void };

let current: Pending | null = null;
let listeners: Array<() => void> = [];

function emit() {
  for (const l of listeners) l();
}

function settle(value: boolean) {
  if (!current) return;
  current.resolve(value);
  current = null;
  emit();
}

/** Promise-based confirm. Resolves true if confirmed, false if cancelled.
 *  Usage: `if (!(await confirm({ message, danger: true }))) return;` */
export function confirm(opts: ConfirmOpts): Promise<boolean> {
  // If a dialog is already open, resolve it as cancelled first.
  if (current) current.resolve(false);
  return new Promise<boolean>((resolve) => {
    current = { ...opts, resolve };
    emit();
  });
}

/** Mount once near the app root (alongside <Toaster/>). */
export function ConfirmHost() {
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    listeners.push(force);
    return () => { listeners = listeners.filter((l) => l !== force); };
  }, []);

  if (!current) return null;
  const { title, message, confirmLabel, cancelLabel, danger } = current;

  return (
    <Modal
      title={title ?? (danger ? 'Are you sure?' : 'Confirm')}
      icon={danger ? Icons.Alert : Icons.Info}
      iconBg={danger ? 'var(--danger-soft)' : 'var(--accent-soft)'}
      iconColor={danger ? 'var(--danger-ink)' : 'var(--accent-ink)'}
      width={440}
      onClose={() => settle(false)}
    >
      <p style={{ fontSize: 14, lineHeight: 1.55, color: 'var(--text-soft)', whiteSpace: 'pre-wrap' }}>{message}</p>
      <div style={{ display: 'flex', gap: 10, marginTop: 22 }}>
        <button type="button" className="btn btn-outline" style={{ flex: 1, padding: '12px 20px', fontWeight: 700 }} onClick={() => settle(false)}>
          {cancelLabel ?? 'Cancel'}
        </button>
        <button
          type="button"
          className="btn"
          style={{ flex: 1, padding: '12px 20px', fontWeight: 700, border: 'none', color: danger ? 'var(--on-danger)' : 'var(--on-accent)', background: danger ? 'var(--danger)' : 'var(--accent)' }}
          onClick={() => settle(true)}
          autoFocus
        >
          {confirmLabel ?? (danger ? 'Delete' : 'Confirm')}
        </button>
      </div>
    </Modal>
  );
}
