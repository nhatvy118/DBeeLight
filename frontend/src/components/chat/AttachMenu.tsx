import { useState } from 'react';
import { Icons, type IconComponent } from '../../icons';

type AttachMenuProps = {
  /** Open the OS file picker (device upload). */
  onUploadDevice: () => void;
  disabled?: boolean;
};

/** The "+" attach button with a popup offering "Upload from device".
 *  Manages its own open state so it can drop into the composer unchanged. */
export default function AttachMenu({ onUploadDevice, disabled }: AttachMenuProps) {
  const [open, setOpen] = useState(false);

  const options: { icon: IconComponent; label: string; sub: string; act: () => void }[] = [
    {
      icon: Icons.Monitor,
      label: 'Upload from device',
      sub: 'Spreadsheets (.xlsx, .xls, .xlsb, .ods, .csv)',
      act: () => { setOpen(false); onUploadDevice(); },
    },
  ];

  return (
    <div style={{ position: 'relative' }}>
      {open && (
        <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 30 }} />
      )}
      {open && (
        <div
          className="card pop-shadow scale-in"
          style={{ position: 'absolute', bottom: 'calc(100% + 8px)', left: 0, zIndex: 31, width: 232, borderRadius: 'var(--r)', padding: 7, transformOrigin: 'bottom left' }}
        >
          {options.map((o) => {
            const Icon = o.icon;
            return (
              <button
                key={o.label}
                type="button"
                onClick={o.act}
                className="focusable"
                style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 11, padding: '9px 10px', borderRadius: 'var(--r-sm)', textAlign: 'left', background: 'transparent', border: 'none', transition: 'background .12s' }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
              >
                <span style={{ width: 32, height: 32, borderRadius: 9, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)', flexShrink: 0 }}>
                  <Icon size={17} />
                </span>
                <span style={{ minWidth: 0 }}>
                  <span style={{ display: 'block', fontSize: 13.5, fontWeight: 600 }}>{o.label}</span>
                  <span style={{ display: 'block', fontSize: 11.5, color: 'var(--text-muted)' }}>{o.sub}</span>
                </span>
              </button>
            );
          })}
        </div>
      )}

      <button
        type="button"
        title="Attach a file"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className="focusable"
        style={{
          width: 36, height: 36, borderRadius: 10, display: 'grid', placeItems: 'center',
          color: open ? 'var(--accent-ink)' : 'var(--text-soft)',
          border: '1px solid var(--border)',
          background: open ? 'var(--accent-soft)' : 'transparent',
          flexShrink: 0, opacity: disabled ? 0.5 : 1, cursor: disabled ? 'default' : 'pointer',
        }}
        onMouseEnter={(e) => { if (!open && !disabled) e.currentTarget.style.background = 'var(--surface-2)'; }}
        onMouseLeave={(e) => { if (!open) e.currentTarget.style.background = 'transparent'; }}
      >
        <Icons.Plus size={19} style={{ transition: 'transform .15s', transform: open ? 'rotate(45deg)' : 'none' }} />
      </button>
    </div>
  );
}
