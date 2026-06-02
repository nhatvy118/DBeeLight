import type { ReactNode } from 'react';
import { Icons, type IconComponent } from '../../icons';

type ModalProps = {
  title: string;
  subtitle?: string;
  icon?: IconComponent;
  onClose: () => void;
  children: ReactNode;
  width?: number;
};

/** Base modal shell — ported from the Chat/ design prototype (Chat/modals.jsx).
 *  Backdrop + card with an icon/title/subtitle header and a close button. */
export default function Modal({ title, subtitle, icon: Icon, onClose, children, width = 520 }: ModalProps) {
  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        className="card pop-shadow scale-in"
        style={{ width: '100%', maxWidth: width, maxHeight: '90vh', overflowY: 'auto', borderRadius: 'var(--r-lg)' }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, padding: '24px 26px 18px' }}>
          {Icon && (
            <div style={{ width: 44, height: 44, borderRadius: 13, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)', flexShrink: 0 }}>
              <Icon size={22} />
            </div>
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-.01em' }}>{title}</h2>
            {subtitle && <p style={{ fontSize: 13.5, color: 'var(--text-muted)', marginTop: 3 }}>{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            className="focusable"
            type="button"
            style={{ width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', background: 'transparent', border: 'none' }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <Icons.Close size={18} />
          </button>
        </div>
        <div style={{ padding: '0 26px 26px' }}>{children}</div>
      </div>
    </div>
  );
}
