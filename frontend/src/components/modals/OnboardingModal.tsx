import { useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Icons, BeeBadge, type IconComponent } from '../../icons';
import { useTheme } from '../../context/ThemeContext';

/* ============================================================
   Onboarding — ported from the design prototype (hi.html / onboarding.jsx).
   Built around LightDBee's two modes:
   A) No database  → create a project, add data by chat or Excel
   B) Have a database → connect it
   Both modes then: ask in natural language, analyze, chart, share.
   ============================================================ */

const I = Icons;

function MiniBubble({ children, you }: { children: ReactNode; you?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: you ? 'flex-end' : 'flex-start' }}>
      <div
        style={{
          maxWidth: '85%', fontSize: 12.5, fontWeight: you ? 600 : 500, lineHeight: 1.4,
          padding: '8px 12px', borderRadius: you ? '13px 13px 4px 13px' : '13px 13px 13px 4px',
          background: you ? 'var(--accent-soft)' : 'var(--surface-2)',
          border: `1px solid ${you ? 'var(--accent-soft-2)' : 'var(--border)'}`, color: 'var(--text)',
        }}
      >
        {children}
      </div>
    </div>
  );
}

type Tint = { bg: string; fg: string };

/* ---- mode card for the "two modes" step ---- */
function ModeCard({ badge, icon: Icon, title, steps, tint }: { badge: string; icon: IconComponent; title: string; steps: ReactNode[]; tint: Tint }) {
  return (
    <div className="card" style={{ flex: 1, padding: 20, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <span style={{ width: 40, height: 40, borderRadius: 11, flexShrink: 0, display: 'grid', placeItems: 'center', background: tint.bg, color: tint.fg }}>
          <Icon size={20} />
        </span>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.05em', textTransform: 'uppercase', color: tint.fg, background: tint.bg, padding: '3px 9px', borderRadius: 99 }}>{badge}</span>
      </div>
      <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: '-.01em', marginBottom: 14 }}>{title}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
        {steps.map((s, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 11 }}>
            <span style={{ width: 22, height: 22, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', background: tint.bg, color: tint.fg, fontSize: 11, fontWeight: 800 }}>{i + 1}</span>
            <span style={{ fontSize: 13.5, color: 'var(--text-soft)', lineHeight: 1.45, paddingTop: 1 }}>{s}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

type Step = {
  art: ReactNode;
  eyebrow: string;
  title: string;
  body: ReactNode;
  wide?: boolean;
};

/* ---------- steps ---------- */
const STEPS: Step[] = [
  /* 0 — welcome */
  {
    art: (
      <div style={{ display: 'grid', placeItems: 'center', gap: 16 }}>
        <BeeBadge size={72} />
        <div style={{ width: '100%', maxWidth: 320, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <MiniBubble you>Which products sold best last month?</MiniBubble>
          <MiniBubble>Lotus Tea leads with $48k. Want a chart?</MiniBubble>
        </div>
      </div>
    ),
    eyebrow: 'Welcome',
    title: 'Talk to your data',
    body: <>LightDBee helps you <strong>work with your data using plain language</strong> — no SQL, no formulas, no database know-how. Just ask, and the bee finds answers, makes changes, and draws charts for you.</>,
  },

  /* 1 — the two modes (the spine) */
  {
    eyebrow: 'The only choice you make',
    title: 'Two ways to begin — Step 1',
    body: <>The <strong>only</strong> difference is how you start. After that, <strong>everything is identical</strong> — ask, edit, analyze and chart, all in natural language.</>,
    wide: true,
    art: (
      <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
          <ModeCard
            badge="No database? No problem" icon={I.Sparkle} title="Let LightDBee hold your data"
            steps={[<>Create a <strong>project</strong> &amp; add data (chat or Excel)</>, <>Ask the bot to <strong>interact with &amp; analyze</strong> your data</>]}
            tint={{ bg: 'var(--accent-soft)', fg: 'var(--accent-ink)' }}
          />
          <ModeCard
            badge="Already have a database" icon={I.Database} title="Connect your own database"
            steps={[<>Connect <strong>PostgreSQL</strong> or <strong>SQLite</strong></>, <>Ask the bot to <strong>interact with &amp; analyze</strong> your data</>]}
            tint={{ bg: 'var(--green-soft)', fg: 'var(--green-ink)' }}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, fontSize: 13, fontWeight: 700, color: 'var(--accent-ink)' }}>
          <span style={{ flex: 1, maxWidth: 70, height: 1, background: 'var(--border)' }} />
          <I.ChevronDown size={16} />
          <span>from here, it's the same for everyone</span>
          <I.ChevronDown size={16} />
          <span style={{ flex: 1, maxWidth: 70, height: 1, background: 'var(--border)' }} />
        </div>
      </div>
    ),
  },

  /* 2 — Mode A: create project + add data */
  {
    art: (
      <div style={{ width: '100%', maxWidth: 330, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '9px 13px', borderRadius: 'var(--r-sm)', border: '1px solid var(--accent-soft-2)', background: 'var(--accent-soft)', color: 'var(--accent-ink)', fontWeight: 700, fontSize: 13.5, width: 'fit-content' }}>
          <I.FolderPlus size={16} />New project
        </div>
        <span style={{ alignSelf: 'center', color: 'var(--text-faint)' }}><I.ChevronDown size={18} /></span>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 10 }}>New project</div>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-soft)', marginBottom: 5 }}>Project name</div>
          <div style={{ display: 'flex', alignItems: 'center', padding: '8px 11px', borderRadius: 8, border: '1.5px solid var(--accent)', background: 'var(--surface)', fontSize: 13, color: 'var(--text)' }}>
            Sales 2025<span style={{ width: 1.5, height: 14, background: 'var(--accent)', marginLeft: 1, animation: 'blink 1.1s step-end infinite' }} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--on-accent)', background: 'var(--accent)', padding: '7px 14px', borderRadius: 99 }}>Create project</span>
          </div>
        </div>
      </div>
    ),
    eyebrow: 'Step 1 · If you have no database',
    title: 'Create a project, add your data',
    body: <>Click <strong>New project</strong> in the sidebar and give it a name. Then add your data simply by chatting — <em>"create a customers table," "add these rows"</em> — or <strong>import an Excel file</strong> and the bee loads it for you.</>,
  },

  /* 3 — Mode B: connect database */
  {
    art: (
      <div style={{ width: '100%', maxWidth: 340 }}>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 13 }}>
            <span style={{ width: 32, height: 32, borderRadius: 9, display: 'grid', placeItems: 'center', background: 'var(--green-soft)', color: 'var(--green-ink)' }}><I.Database size={17} /></span>
            <span style={{ fontSize: 13.5, fontWeight: 700 }}>Connect your data</span>
          </div>
          <div style={{ display: 'flex', gap: 7, marginBottom: 12 }}>
            {['PostgreSQL', 'SQLite'].map((e, i) => (
              <span key={e} style={{ flex: 1, textAlign: 'center', fontSize: 11.5, fontWeight: 700, padding: '7px', borderRadius: 8, border: `1.5px solid ${i === 0 ? 'var(--accent)' : 'var(--border)'}`, background: i === 0 ? 'var(--accent-soft)' : 'var(--surface)', color: i === 0 ? 'var(--accent-ink)' : 'var(--text-soft)' }}>{e}</span>
            ))}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            {([['Host', 'db.mycompany.com'], ['Database', 'shop_analytics'], ['Username', 'analyst'], ['Password', '••••••••']] as const).map(([l, v]) => (
              <div key={l} style={{ display: 'grid', gridTemplateColumns: '70px 1fr', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-muted)', textAlign: 'right' }}>{l}</span>
                <span style={{ fontSize: 11.5, color: 'var(--text-soft)', padding: '6px 9px', borderRadius: 7, background: 'var(--surface-2)', border: '1px solid var(--border)', fontFamily: 'var(--font-mono)' }}>{v}</span>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, marginTop: 13, fontSize: 12.5, fontWeight: 700, color: 'var(--on-accent)', background: 'var(--accent)', padding: '9px', borderRadius: 99 }}>
            <I.Lightning size={14} />Test &amp; connect
          </div>
        </div>
      </div>
    ),
    eyebrow: 'Step 1 · If you have a database',
    title: 'Connect your database',
    body: <>Already have data in a database? Click <strong>Connect data</strong>, choose <strong>PostgreSQL</strong> or <strong>SQLite</strong>, enter your details and hit <strong>Test &amp; connect</strong>. From there you can do <strong>everything</strong> — ask, add, edit and analyze — just like a project. Your credentials stay encrypted, and the bee always shows its plan before making changes.</>,
  },

  /* 4 — ask, interact & stay in control */
  {
    art: (
      <div style={{ width: '100%', maxWidth: 350, display: 'flex', flexDirection: 'column', gap: 9 }}>
        <MiniBubble you>Remove customers with no orders</MiniBubble>
        <div className="card" style={{ overflow: 'hidden', borderColor: 'var(--accent-soft-2)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', background: 'var(--accent-soft)', borderBottom: '1px solid var(--accent-soft-2)' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 11, fontWeight: 700, color: 'var(--accent-ink)' }}><I.Code size={13} />Proposed query — review before running</span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 600, color: 'var(--text-soft)' }}><I.Copy size={12} />Copy</span>
          </div>
          <pre style={{ margin: 0, padding: '11px 13px', background: 'var(--surface)', fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.65, color: 'var(--text-soft)', overflowX: 'auto' }}>{'DELETE FROM customers\nWHERE id NOT IN (\n  SELECT customer_id FROM orders\n);'}</pre>
          <div style={{ display: 'flex', gap: 9, alignItems: 'flex-start', padding: '10px 12px', background: 'var(--accent-soft)', borderTop: '1px solid var(--accent-soft-2)' }}>
            <span style={{ color: 'var(--accent-ink)', flexShrink: 0, marginTop: 1 }}><I.Sparkle size={14} /></span>
            <span style={{ fontSize: 12, lineHeight: 1.45, color: 'var(--text)' }}><strong>In natural language:</strong> removes every customer who has never placed an order.</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, padding: '10px 12px', borderTop: '1px solid var(--border)' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-muted)' }}><I.Info size={13} />Read-only · nothing changes without your OK</span>
            <span style={{ display: 'flex', gap: 7 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-soft)', padding: '7px 14px', borderRadius: 99, border: '1px solid var(--border-strong)' }}>Cancel</span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 700, color: 'var(--on-accent)', padding: '7px 14px', borderRadius: 99, background: 'var(--accent)' }}><I.Lightning size={13} />Execute</span>
            </span>
          </div>
        </div>
      </div>
    ),
    eyebrow: 'Same for both · Step 2',
    title: 'Ask, edit & stay in control',
    body: <>Tell the bee what you want — <em>"add a row," "find duplicates," "what's my best month?"</em> Before anything changes, it <strong>shows you the plan in natural language</strong>. Nothing happens until you tap <strong>Execute</strong>.</>,
  },

  /* 5 — analyze & visualize */
  {
    art: (
      <div style={{ width: '100%', maxWidth: 360, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <MiniBubble you>Analyze revenue by region and chart it</MiniBubble>
        <div className="card" style={{ padding: '14px 16px' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 10 }}>Revenue by region</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {([['South', 100], ['North', 72], ['Central', 54]] as const).map(([r, w], i) => (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: '52px 1fr', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 11, color: 'var(--text-soft)', fontWeight: 600, textAlign: 'right' }}>{r}</span>
                <div style={{ height: 18, width: `${w}%`, background: i === 0 ? 'var(--accent)' : 'var(--accent-soft-2)', borderRadius: 5 }} />
              </div>
            ))}
          </div>
        </div>
        <MiniBubble>The South leads — 41% of total revenue, up 12% since Q1.</MiniBubble>
      </div>
    ),
    eyebrow: 'Same for both · Step 3',
    title: 'Analyze & visualize',
    body: <>Ask the bee to <strong>analyze</strong> your data and <strong>draw a chart</strong> — bar, line or pie. You get the picture <em>and</em> a short written takeaway, and can download either to Excel.</>,
  },

];

type OnboardingModalProps = {
  open: boolean;
  /** Called when the user closes/skips/finishes the tour. */
  onClose: () => void;
};

/** Welcome / product tour — shown on first login and from Help & support. */
export default function OnboardingModal({ open, onClose }: OnboardingModalProps) {
  const [i, setI] = useState(0);
  const { theme, toggleTheme } = useTheme();
  const dark = theme === 'dark';

  if (!open) return null;

  const step = STEPS[i];
  const last = i === STEPS.length - 1;
  const next = () => setI((v) => Math.min(v + 1, STEPS.length - 1));
  const back = () => setI((v) => Math.max(v - 1, 0));
  const finish = () => { setI(0); onClose(); };

  const ThemeIcon = dark ? I.Sun : I.Moon;

  const cardStyle: CSSProperties = {
    width: '100%', maxWidth: step.wide ? 780 : 560, borderRadius: 'var(--r-lg)',
    overflow: 'hidden', maxHeight: '92vh', overflowY: 'auto', transition: 'max-width .3s ease',
  };

  const overlay = (
    <div
      onMouseDown={(e) => { if (e.target === e.currentTarget) finish(); }}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'oklch(0.2 0.02 70 / .42)', backdropFilter: 'blur(3px)', WebkitBackdropFilter: 'blur(3px)',
        display: 'flex', justifyContent: 'center', alignItems: 'center', padding: 24,
        animation: 'bgFade .18s ease both',
      }}
    >
      <div className="card pop-shadow scale-in" onMouseDown={(e) => e.stopPropagation()} style={cardStyle}>
        {/* top bar */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 22px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <BeeBadge size={28} /><span style={{ fontSize: 16, fontWeight: 800, letterSpacing: '-.02em' }}>LightDBee</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <button onClick={toggleTheme} type="button" aria-label="Toggle theme" className="focusable" style={{ width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center', color: 'var(--text-soft)', background: 'transparent', border: 'none' }}>
              <ThemeIcon size={17} />
            </button>
            {!last && <button onClick={finish} type="button" className="focusable" style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text-muted)', padding: '6px 4px', background: 'transparent', border: 'none' }}>Skip</button>}
            <button onClick={finish} type="button" aria-label="Close" className="focusable" style={{ width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', background: 'transparent', border: 'none' }}>
              <I.Close size={18} />
            </button>
          </div>
        </div>

        {/* art panel */}
        <div style={{ padding: '36px 30px', display: 'grid', placeItems: 'center', minHeight: 230, background: 'var(--bg-tint)' }}>
          <div key={i} className="fade-up" style={{ width: '100%', display: 'grid', placeItems: 'center' }}>{step.art}</div>
        </div>

        {/* copy */}
        <div style={{ padding: '26px 30px 8px', textAlign: step.wide ? 'center' : 'left' }}>
          <div className="fade-up" style={{ fontSize: 12, fontWeight: 700, letterSpacing: '.07em', textTransform: 'uppercase', color: 'var(--accent-ink)' }}>{step.eyebrow}</div>
          <h1 className="fade-up" style={{ fontSize: 25, fontWeight: 800, letterSpacing: '-.02em', marginTop: 6, animationDelay: '.04s' }}>{step.title}</h1>
          <p className="fade-up" style={{ fontSize: 15.5, color: 'var(--text-soft)', lineHeight: 1.6, marginTop: 9, maxWidth: step.wide ? 560 : 'none', marginInline: step.wide ? 'auto' : 0, animationDelay: '.08s' }}>{step.body}</p>
        </div>

        {/* footer: dots + nav */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '22px 30px 26px' }}>
          <div style={{ display: 'flex', gap: 7 }}>
            {STEPS.map((_, k) => (
              <button key={k} onClick={() => setI(k)} type="button" aria-label={`Step ${k + 1}`} className="focusable" style={{ width: k === i ? 26 : 8, height: 8, borderRadius: 99, border: 'none', padding: 0, cursor: 'pointer', background: k === i ? 'var(--accent)' : 'var(--surface-3)', transition: 'all .2s' }} />
            ))}
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            {i > 0 && <button onClick={back} type="button" className="btn btn-outline" style={{ padding: '11px 18px' }}>Back</button>}
            <button onClick={last ? finish : next} type="button" className="btn btn-primary" style={{ padding: '11px 22px' }}>
              {last ? <><I.Lightning size={16} />Start using LightDBee</> : <>Next<I.ChevronRight size={16} /></>}
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(overlay, document.body);
}
