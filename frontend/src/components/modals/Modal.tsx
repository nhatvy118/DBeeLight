import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Icons, type IconComponent } from '../../icons';
import { useIsMobile } from '../../hooks/useIsMobile';

type ModalProps = {
  title: string;
  subtitle?: string;
  icon?: IconComponent;
  onClose: () => void;
  children: ReactNode;
  width?: number;
};

/** Base modal shell — ported from the Chat/ design prototype (Chat/modals.jsx).
 *
 *  - Desktop: centered card.
 *  - Mobile: a bottom sheet that slides up (Chat/mobile.jsx ConnectSheet).
 *
 *  Always rendered through a portal to ``document.body`` so it escapes any
 *  ``transform``ed ancestor (e.g. the mobile sidebar drawer) — a fixed element
 *  inside a transformed parent would otherwise be clipped to that parent. */
export default function Modal({ title, subtitle, icon: Icon, onClose, children, width = 520 }: ModalProps) {
  const isMobile = useIsMobile();

  const overlay = (
    <div
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'oklch(0.2 0.02 70 / .42)', backdropFilter: 'blur(3px)', WebkitBackdropFilter: 'blur(3px)',
        display: 'flex', justifyContent: 'center',
        alignItems: isMobile ? 'flex-end' : 'center',
        padding: isMobile ? 0 : 24,
        animation: 'bgFade .18s ease both',
      }}
    >
      <div
        className={`card pop-shadow ${isMobile ? 'sheet-up' : 'scale-in'}`}
        onMouseDown={(e) => e.stopPropagation()}
        style={
          isMobile
            ? { width: '100%', maxHeight: '92vh', overflowY: 'auto', borderRadius: '22px 22px 0 0', paddingBottom: 'env(safe-area-inset-bottom)' }
            : { width: '100%', maxWidth: width, maxHeight: '90vh', overflowY: 'auto', borderRadius: 'var(--r-lg)' }
        }
      >
        {/* Drag handle (mobile bottom-sheet affordance) */}
        {isMobile && (
          <div style={{ width: 38, height: 4, borderRadius: 99, background: 'var(--border-strong)', margin: '10px auto 0' }} />
        )}

        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, padding: isMobile ? '16px 20px 14px' : '24px 26px 18px' }}>
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
          >
            <Icons.Close size={18} />
          </button>
        </div>
        <div style={{ padding: isMobile ? '0 20px 22px' : '0 26px 26px' }}>{children}</div>
      </div>
    </div>
  );

  return createPortal(overlay, document.body);
}
