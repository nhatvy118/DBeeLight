import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import Modal from './Modal';
import { Icons, type IconComponent } from '../../icons';
import { getSessions } from '../../services/api';

const DANGER = 'var(--danger)';
const DANGER_INK = 'var(--danger-ink)';
const DANGER_SOFT = 'var(--danger-soft)';
const DANGER_BORDER = 'var(--danger-border)';
const ON_DANGER = 'var(--on-danger)';

type Props = {
  projectId: string;
  projectName: string;
  isDeleting: boolean;
  onClose: () => void;
  onConfirm: () => void;
};

function Line({ icon: Icon, children }: { icon: IconComponent; children: ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
      <span style={{ width: 38, height: 38, borderRadius: 9, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--surface-2)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>
        <Icon size={17} />
      </span>
      <span style={{ fontSize: 14.5, color: 'var(--text)', lineHeight: 1.4 }}>{children}</span>
    </div>
  );
}

export default function DeleteProjectModal({ projectId, projectName, isDeleting, onClose, onConfirm }: Props) {
  const [sessionCount, setSessionCount] = useState<number | null>(null);
  const [confirmText, setConfirmText] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getSessions(projectId);
        if (!cancelled && res.success) setSessionCount((res.sessions || []).length);
      } catch { /* best-effort */ }
    })();
    return () => { cancelled = true; };
  }, [projectId]);

  const confirmed = confirmText.trim() === projectName.trim();
  const canDelete = confirmed && !isDeleting;

  const sessionLine = sessionCount === null
    ? 'All chat sessions and their full history'
    : `${sessionCount} chat session${sessionCount === 1 ? '' : 's'} and their full history`;

  return (
    <Modal
      title="Delete this project?"
      subtitle={<>You're about to permanently delete <strong style={{ color: 'var(--text)', fontWeight: 700 }}>{projectName}</strong>.</>}
      icon={Icons.Trash}
      iconBg={DANGER_SOFT}
      iconColor={DANGER_INK}
      width={500}
      onClose={() => { if (!isDeleting) onClose(); }}
    >
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 14 }}>
        This will permanently remove
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Line icon={Icons.Pencil}>{sessionLine}</Line>
        <Line icon={Icons.File}>Uploaded files and generated exports</Line>
        <Line icon={Icons.Database}>The project database</Line>
      </div>

      {/* Type-to-confirm */}
      <div style={{ marginTop: 22, padding: 16, borderRadius: 'var(--r)', background: DANGER_SOFT, border: `1px solid ${DANGER_BORDER}` }}>
        <label htmlFor="delete-project-confirm" style={{ display: 'block', fontSize: 13.5, color: 'var(--text-soft)', marginBottom: 9 }}>
          Type <strong style={{ color: DANGER_INK, fontWeight: 700 }}>{projectName}</strong> to confirm
        </label>
        <input
          id="delete-project-confirm"
          type="text"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && canDelete) onConfirm(); }}
          placeholder={projectName}
          autoFocus
          autoComplete="off"
          disabled={isDeleting}
          className="focusable"
          style={{ width: '100%', padding: '12px 14px', fontSize: 14.5, borderRadius: 'var(--r-sm)', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', outline: 'none' }}
        />
      </div>

      <div style={{ display: 'flex', gap: 10, marginTop: 22 }}>
        <button
          type="button"
          className="btn btn-outline"
          style={{ flex: 1, padding: '12px 20px', fontWeight: 700 }}
          disabled={isDeleting}
          onClick={onClose}
        >
          Keep project
        </button>
        <button
          type="button"
          className="btn"
          style={{ flex: 1, padding: '12px 20px', fontWeight: 700, border: 'none', color: canDelete ? ON_DANGER : 'var(--text-muted)', background: canDelete ? DANGER : 'var(--surface-3)', cursor: canDelete ? 'pointer' : 'not-allowed', opacity: canDelete ? 1 : 0.75 }}
          disabled={!canDelete}
          onClick={onConfirm}
        >
          <Icons.Trash size={16} /> {isDeleting ? 'Deleting…' : 'Delete forever'}
        </button>
      </div>
    </Modal>
  );
}
