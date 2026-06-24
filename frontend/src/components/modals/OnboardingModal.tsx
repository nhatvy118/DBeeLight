import { createPortal } from 'react-dom';
import { Icons, type IconComponent } from '../../icons';
import { useAuth } from '../../context/AuthContext';

/* ============================================================
   Role-aware onboarding — a single welcome card whose content
   depends on the signed-in user's role (admin / technical / viewer).
   Ported from the roles design prototype (RoleWelcome).
   ============================================================ */

type Role = 'admin' | 'technical' | 'viewer';

type RoleMeta = {
  label: string; icon: IconComponent; desc: string; cta: string;
  ink: string; soft: string; solid: string;
};

const ROLE_META: Record<Role, RoleMeta> = {
  admin: {
    label: 'Admin', icon: Icons.ShieldUser, cta: 'Open the dashboard',
    desc: 'Manage people and their roles across the workspace — who can build with data and who can only explore.',
    ink: 'oklch(0.48 0.15 285)', soft: 'oklch(0.95 0.035 285)', solid: 'oklch(0.55 0.16 285)',
  },
  technical: {
    label: 'Technical', icon: Icons.Code, cta: 'Start building',
    desc: 'Connect databases, create projects, run full read & write operations, and share data with your team.',
    ink: 'oklch(0.46 0.12 55)', soft: 'oklch(0.95 0.04 70)', solid: 'oklch(0.62 0.13 60)',
  },
  viewer: {
    label: 'Non-technical', icon: Icons.Eye, cta: 'Explore my shared projects',
    desc: 'Open projects shared with you and ask questions in plain English. Read results — never change data.',
    ink: 'oklch(0.44 0.1 155)', soft: 'oklch(0.95 0.04 155)', solid: 'oklch(0.56 0.12 155)',
  },
};

type Point = { icon: IconComponent; t: string; d: string };
const ROLE_INTRO: Record<Role, Point[]> = {
  admin: [
    { icon: Icons.Users, t: 'Manage everyone', d: 'Assign each person a role — Admin, Technical or Non-technical — from one place.' },
    { icon: Icons.ShieldUser, t: 'Set the boundaries', d: 'Roles decide who can connect data, who can build, and who can only explore.' },
    { icon: Icons.Plus, t: 'Invite people', d: 'Add teammates by email and pick their role from day one.' },
  ],
  technical: [
    { icon: Icons.Database, t: 'Connect your data', d: 'Link a PostgreSQL database, or build tables from Excel.' },
    { icon: Icons.FolderPlus, t: 'Create projects', d: 'Group data and chats. Ask, edit, analyze and chart — in plain language.' },
    { icon: Icons.Share, t: 'Share the data', d: 'Invite non-technical teammates to a project. They get to explore the data — read-only.' },
  ],
  viewer: [
    { icon: Icons.Share, t: "Open what's shared", d: 'Projects your team shares with you appear right here on your home.' },
    { icon: Icons.Question, t: 'Just ask', d: 'Type a question in plain English — get a clear answer, table and chart. No SQL, ever.' },
    { icon: Icons.Eye, t: 'Safe to explore', d: 'You can read and analyze everything, but you can never change the data.' },
  ],
};

type OnboardingModalProps = {
  open: boolean;
  /** Called when the user closes/finishes onboarding. */
  onClose: () => void;
};

/** Welcome card — shown on first login and from Help & support. Content is role-specific. */
export default function OnboardingModal({ open, onClose }: OnboardingModalProps) {
  const { user } = useAuth();
  if (!open) return null;

  const role: Role = (user?.role as Role) || (user?.is_admin ? 'admin' : 'technical');
  const m = ROLE_META[role];
  const points = ROLE_INTRO[role];
  const Icon = m.icon;

  const overlay = (
    <div
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'oklch(0.2 0.02 70 / .42)', backdropFilter: 'blur(3px)', WebkitBackdropFilter: 'blur(3px)',
        display: 'flex', justifyContent: 'center', alignItems: 'center', padding: 24,
        animation: 'bgFade .18s ease both',
      }}
    >
      <div className="card pop-shadow scale-in" onMouseDown={(e) => e.stopPropagation()} style={{ width: '100%', maxWidth: 480, borderRadius: 'var(--r-lg)', overflow: 'hidden', maxHeight: '92vh', overflowY: 'auto' }}>
        {/* role-coloured header */}
        <div style={{ padding: '28px 28px 22px', background: m.soft, position: 'relative' }}>
          <button type="button" onClick={onClose} aria-label="Close" className="focusable" style={{ position: 'absolute', top: 16, right: 16, width: 32, height: 32, borderRadius: 9, display: 'grid', placeItems: 'center', color: m.ink, background: 'transparent', border: 'none', cursor: 'pointer' }}>
            <Icons.Close size={18} />
          </button>
          <div style={{ width: 52, height: 52, borderRadius: 15, display: 'grid', placeItems: 'center', background: m.solid, color: '#fff', marginBottom: 16 }}>
            <Icon size={27} />
          </div>
          <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: m.ink }}>Welcome — you're set up as</div>
          <h2 style={{ fontSize: 25, fontWeight: 800, letterSpacing: '-.02em', marginTop: 4, color: 'var(--text)' }}>{m.label}</h2>
          <p style={{ fontSize: 14.5, color: 'var(--text-soft)', marginTop: 7, lineHeight: 1.5 }}>{m.desc}</p>
        </div>

        {/* role points */}
        <div style={{ padding: '20px 26px 8px', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {points.map((pt, i) => {
            const PIcon = pt.icon;
            return (
              <div key={i} style={{ display: 'flex', gap: 14, padding: '12px 6px', borderTop: i ? '1px solid var(--border)' : 'none' }}>
                <span style={{ width: 36, height: 36, borderRadius: 10, flexShrink: 0, display: 'grid', placeItems: 'center', background: m.soft, color: m.ink }}><PIcon size={18} /></span>
                <span style={{ minWidth: 0 }}>
                  <span style={{ display: 'block', fontSize: 14.5, fontWeight: 700 }}>{pt.t}</span>
                  <span style={{ display: 'block', fontSize: 13, color: 'var(--text-muted)', marginTop: 2, lineHeight: 1.45 }}>{pt.d}</span>
                </span>
              </div>
            );
          })}
        </div>

        {/* CTA */}
        <div style={{ padding: '12px 26px 24px' }}>
          <button type="button" onClick={onClose} className="btn" style={{ width: '100%', padding: '13px', background: m.solid, color: '#fff', fontWeight: 700, border: 'none' }}>
            {m.cta}
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(overlay, document.body);
}
