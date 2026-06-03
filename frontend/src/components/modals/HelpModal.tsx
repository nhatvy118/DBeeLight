import Modal from './Modal';
import { Icons, type IconComponent } from '../../icons';

type HelpModalProps = {
  open: boolean;
  onClose: () => void;
};

const TOPICS: { icon: IconComponent; title: string; desc: string }[] = [
  { icon: Icons.Sparkle, title: 'Getting started', desc: 'A 2-minute tour of LightDBee' },
  { icon: Icons.Database, title: 'Connecting your database', desc: 'PostgreSQL & MySQL setup' },
  { icon: Icons.Question, title: 'Asking good questions', desc: 'Tips for clear, accurate answers' },
  { icon: Icons.Share, title: 'Sharing chats & permissions', desc: 'View, Read, and Edit access' },
  { icon: Icons.Download, title: 'Exporting to Excel', desc: 'Download any result as a file' },
];

/** Help & support modal — ported from the Chat/ design prototype (modals.jsx). */
export default function HelpModal({ open, onClose }: HelpModalProps) {
  if (!open) return null;
  return (
    <Modal title="Help & support" subtitle="Find answers or reach our team." icon={Icons.Question} onClose={onClose} width={560}>
      {/* search */}
      <div style={{ position: 'relative', marginBottom: 22 }}>
        <span style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }}>
          <Icons.Search size={18} />
        </span>
        <input className="field focusable" placeholder="Search help articles…" style={{ paddingLeft: 42 }} />
      </div>

      {/* popular topics */}
      <div style={{ fontSize: 12.5, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 10 }}>
        Popular topics
      </div>
      <div className="card" style={{ overflow: 'hidden', marginBottom: 22 }}>
        {TOPICS.map((tp, i) => {
          const Icon = tp.icon;
          return (
            <button
              key={tp.title}
              type="button"
              className="focusable"
              style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 13, padding: '13px 16px', textAlign: 'left', background: 'transparent', border: 'none', borderTop: i ? '1px solid var(--border)' : 'none', transition: 'background .12s' }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
            >
              <span style={{ width: 36, height: 36, borderRadius: 10, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}>
                <Icon size={18} />
              </span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: 'block', fontSize: 14.5, fontWeight: 600 }}>{tp.title}</span>
                <span style={{ display: 'block', fontSize: 12.5, color: 'var(--text-muted)' }}>{tp.desc}</span>
              </span>
              <Icons.ChevronRight size={17} style={{ color: 'var(--text-faint)', flexShrink: 0 }} />
            </button>
          );
        })}
      </div>

      {/* contact */}
      <div style={{ fontSize: 12.5, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 10 }}>
        Still need help?
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ width: 38, height: 38, borderRadius: 11, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)', marginBottom: 11 }}>
            <Icons.Sparkle size={19} />
          </div>
          <div style={{ fontSize: 14.5, fontWeight: 700 }}>Chat with us</div>
          <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginTop: 2 }}>Typically replies in a few minutes</div>
        </div>
        <a href="mailto:support@lightdbee.app" className="card focusable" style={{ padding: 16, textDecoration: 'none', color: 'inherit', display: 'block', transition: 'all .14s' }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.background = 'var(--accent-soft)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.background = 'var(--surface)'; }}>
          <div style={{ width: 38, height: 38, borderRadius: 11, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)', marginBottom: 11 }}>
            <Icons.Share size={19} />
          </div>
          <div style={{ fontSize: 14.5, fontWeight: 700 }}>Email support</div>
          <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginTop: 2 }}>support@lightdbee.app</div>
        </a>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border)', fontSize: 12.5, color: 'var(--text-muted)' }}>
        <span>LightDBee · v2.0</span>
      </div>
    </Modal>
  );
}
