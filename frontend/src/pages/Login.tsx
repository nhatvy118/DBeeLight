import { url } from '../services/api';
import { useTheme } from '../context/ThemeContext';
import { Icons, BeeBadge } from '../icons';

const FEATURES: { icon: keyof typeof Icons; text: string }[] = [
  { icon: 'Question', text: 'Ask in plain English — no SQL needed' },
  { icon: 'Chart', text: 'Instant tables and charts' },
  { icon: 'Download', text: 'Export any answer to Excel' },
];

const PREVIEW_BARS: [string, number][] = [
  ['Lotus Retail', 100],
  ['Mekong Foods', 81],
  ['Hanoi Lighting', 71],
];

export default function Login() {
  const { theme, toggleTheme } = useTheme();

  const handleLoginWithGoogle = () => {
    window.location.href = url(`/api/auth/google/login?next=${encodeURIComponent('/chat')}`);
  };

  return (
    <div className="login-split">
      {/* ---- left: brand showcase ---- */}
      <div className="login-hero">
        <div className="login-blob" style={{ width: 360, height: 360, right: -120, bottom: -120, background: 'oklch(1 0 0 / .18)' }} />
        <div className="login-blob" style={{ width: 200, height: 200, left: -60, top: 120, background: 'oklch(1 0 0 / .12)' }} />

        <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 12 }}>
          <BeeBadge size={44} />
          <span className="ink" style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-.02em' }}>DBeeLight</span>
        </div>

        <div style={{ position: 'relative' }}>
          <h1 className="ink" style={{ fontSize: 48, fontWeight: 800, letterSpacing: '-.03em', lineHeight: 1.05, textWrap: 'balance' }}>
            Talk to your data.
          </h1>
          <p className="ink-soft" style={{ fontSize: 19, marginTop: 16, maxWidth: 420, lineHeight: 1.5 }}>
            Connect a database, ask a question, and get answers as clear tables and charts — in seconds.
          </p>

          {/* floating product preview */}
          <div className="glass scale-in" style={{ marginTop: 34, maxWidth: 400, padding: 18 }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '6px 11px', borderRadius: 99, background: 'oklch(0.30 0.07 55 / .1)', marginBottom: 14 }}>
              <span style={{ width: 7, height: 7, borderRadius: 99, background: 'oklch(0.55 0.13 150)' }} />
              <span className="ink" style={{ fontSize: 12, fontWeight: 700 }}>shop_analytics</span>
            </div>
            <div className="ink" style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>Who are my top customers?</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
              {PREVIEW_BARS.map((r, i) => (
                <div key={i} style={{ display: 'grid', gridTemplateColumns: '92px 1fr', alignItems: 'center', gap: 10 }}>
                  <span className="ink-soft" style={{ fontSize: 12, fontWeight: 600, textAlign: 'right' }}>{r[0]}</span>
                  <div style={{ height: 18, width: `${r[1]}%`, borderRadius: 5, background: 'linear-gradient(90deg, oklch(0.66 0.16 55), oklch(0.78 0.14 78))' }} />
                </div>
              ))}
            </div>
          </div>
        </div>

        <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', gap: 11 }}>
          {FEATURES.map((f, i) => {
            const Icon = Icons[f.icon];
            return (
              <div key={i} className="ink" style={{ display: 'flex', alignItems: 'center', gap: 11, fontSize: 14.5, fontWeight: 600 }}>
                <span style={{ width: 28, height: 28, borderRadius: 8, display: 'grid', placeItems: 'center', background: 'oklch(1 0 0 / .35)', flexShrink: 0 }}>
                  <Icon size={16} />
                </span>
                {f.text}
              </div>
            );
          })}
        </div>
      </div>

      {/* ---- right: sign in ---- */}
      <div className="login-pane">
        <button
          onClick={toggleTheme}
          title="Toggle theme"
          className="focusable"
          style={{ position: 'absolute', top: 20, right: 20, width: 40, height: 40, borderRadius: 11, display: 'grid', placeItems: 'center', color: 'var(--text-soft)', border: '1px solid var(--border)', background: 'var(--surface)' }}
        >
          {theme === 'dark' ? <Icons.Sun size={18} /> : <Icons.Moon size={18} />}
        </button>

        <div className="fade-up" style={{ width: '100%', maxWidth: 380 }}>
          <h2 style={{ fontSize: 30, fontWeight: 800, letterSpacing: '-.02em' }}>Welcome back</h2>
          <p style={{ fontSize: 15.5, color: 'var(--text-soft)', marginTop: 8 }}>Sign in to pick up where you left off.</p>

          <button
            type="button"
            className="btn focusable"
            style={{ width: '100%', padding: 15, marginTop: 30, fontSize: 15, background: 'var(--surface)', border: '1.5px solid var(--border-strong)', borderRadius: 14, boxShadow: '0 1px 2px hsl(var(--shadow-color)/.15)' }}
            onClick={handleLoginWithGoogle}
          >
            <span style={{ width: 22, height: 22, borderRadius: 99, background: 'conic-gradient(from -45deg, #ea4335 0 25%, #fbbc05 0 50%, #34a853 0 75%, #4285f4 0)', flexShrink: 0, display: 'inline-block' }} />
            <span style={{ fontWeight: 700 }}>Continue with Google</span>
          </button>

          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 9, marginTop: 18, padding: '12px 14px', borderRadius: 12, background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
            <Icons.Info size={16} style={{ color: 'var(--accent-ink)', flexShrink: 0, marginTop: 1 }} />
            <span style={{ fontSize: 12.5, color: 'var(--text-soft)', lineHeight: 1.5 }}>
              We use Google to sign you in securely — no password to remember.
            </span>
          </div>

          <p style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 26, lineHeight: 1.6 }}>
            By continuing, you agree to our{' '}
            <a href="#" onClick={(e) => e.preventDefault()} style={{ color: 'var(--accent-ink)', fontWeight: 600, textDecoration: 'none' }}>Terms</a>
            {' '}and{' '}
            <a href="#" onClick={(e) => e.preventDefault()} style={{ color: 'var(--accent-ink)', fontWeight: 600, textDecoration: 'none' }}>Service Policy</a>.
          </p>
        </div>
      </div>
    </div>
  );
}
