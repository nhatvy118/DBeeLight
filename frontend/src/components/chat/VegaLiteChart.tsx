import { useEffect, useMemo, useRef, useState } from 'react';
import { VegaEmbed } from 'react-vega';
import { useTheme } from '../../context/ThemeContext';
import { Icons } from '../../icons';

type VegaLiteChartProps = {
  /** Raw JSON string of a Vega-Lite v5 spec, taken from a `generate_chart`
   * tool_event payload (detected by tool name, not message-text markers). */
  specJson: string;
  /** When provided, the menu shows "Save to dashboard". Receives the user-chosen title. */
  onSave?: (title: string) => boolean | void | Promise<boolean | void>;
  /** Whether this chart is already saved (shows a "Saved" state). */
  saved?: boolean;
  /** When provided, renders an editable title inside the card (for dashboard use). */
  editableTitle?: string;
  /** Called when the user finishes editing the title. */
  onTitleSave?: (title: string) => void;
};

/** Read a CSS custom property off :root, falling back when unset/SSR. */
function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/** Build a Vega config that matches the app's design tokens (honey accent,
 * Plus Jakarta Sans, soft grid) and follows light/dark + accent themes. Keyed
 * on `theme` so it recomputes when the user toggles the theme. */
function useVegaConfig(theme: string) {
  return useMemo(() => {
    const accent = cssVar('--accent', 'oklch(0.80 0.135 78)');
    const text = cssVar('--text', theme === 'dark' ? '#f5f3ef' : '#26211a');
    const textSoft = cssVar('--text-soft', '#5b554c');
    const textMuted = cssVar('--text-muted', '#8a8378');
    const border = cssVar('--border', theme === 'dark' ? '#4a443c' : '#e6e2d9');

    // Categorical palette: brand colours first, then harmonious oklch hues.
    const category = [
      accent,
      cssVar('--info', 'oklch(0.62 0.11 245)'),
      cssVar('--green', 'oklch(0.60 0.11 156)'),
      'oklch(0.62 0.17 300)', // violet
      'oklch(0.66 0.16 25)', // coral
      'oklch(0.66 0.11 200)', // teal
      'oklch(0.60 0.16 350)', // magenta
      cssVar('--accent-strong', 'oklch(0.72 0.15 68)'),
    ];
    const font = '"Plus Jakarta Sans", system-ui, sans-serif';

    return {
      background: 'transparent',
      font,
      padding: 6,
      view: { stroke: 'transparent' },
      autosize: { type: 'fit', contains: 'padding' },
      title: { color: text, font, fontSize: 14, fontWeight: 700, anchor: 'start', offset: 12 },
      axis: {
        labelColor: textMuted,
        titleColor: textSoft,
        labelFont: font,
        titleFont: font,
        labelFontSize: 11,
        titleFontSize: 12,
        titleFontWeight: 600,
        gridColor: border,
        gridOpacity: 0.7,
        gridDash: [2, 3],
        domain: false,
        ticks: false,
        labelPadding: 6,
        titlePadding: 10,
      },
      axisX: { grid: false },
      legend: {
        orient: 'bottom',
        labelColor: textSoft,
        titleColor: textSoft,
        labelFont: font,
        titleFont: font,
        labelFontSize: 11,
        titleFontSize: 11,
        symbolType: 'circle',
        symbolSize: 70,
      },
      range: { category, ramp: [cssVar('--accent-soft', '#fbe7c8'), accent] },
      mark: { tooltip: true },
      bar: { cornerRadiusEnd: 4, color: accent },
      line: { strokeWidth: 2.5, color: accent },
      point: { filled: true, size: 70, color: accent },
      area: { line: true, opacity: 0.85, color: accent },
      arc: { innerRadius: 45, stroke: cssVar('--surface', '#fff'), strokeWidth: 1.5 },
      rect: { color: accent },
    };
  }, [theme]);
}

/** Renders a Vega-Lite v5 spec inline in chat. Falls back to a code-block
 * style error display when the spec is malformed. */
export default function VegaLiteChart({ specJson, onSave, saved = false, editableTitle, onTitleSave }: VegaLiteChartProps) {
  const { theme } = useTheme();
  const config = useVegaConfig(theme);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [pendingTitle, setPendingTitle] = useState('');
  const [titleEditing, setTitleEditing] = useState(false);
  const [titleValue, setTitleValue] = useState(editableTitle ?? '');

  const triggerDownload = (href: string, filename: string) => {
    const a = document.createElement('a');
    a.href = href; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
  };

  // Export the rendered chart (renderer='svg' → there's an <svg> in the DOM). SVG = serialize it;
  // PNG = draw that SVG onto a canvas. Avoids needing the internal Vega view.
  const download = (format: 'png' | 'svg') => {
    setMenuOpen(false);
    const svg = wrapRef.current?.querySelector('svg');
    if (!svg) return;
    const xml = new XMLSerializer().serializeToString(svg);
    const svgBlob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' });
    const svgUrl = URL.createObjectURL(svgBlob);
    if (format === 'svg') {
      triggerDownload(svgUrl, 'chart.svg');
      URL.revokeObjectURL(svgUrl);
      return;
    }
    const scale = 2;
    const w = svg.clientWidth || parseInt(svg.getAttribute('width') || '600', 10);
    const h = svg.clientHeight || parseInt(svg.getAttribute('height') || '340', 10);
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = w * scale; canvas.height = h * scale;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.scale(scale, scale);
        ctx.drawImage(img, 0, 0, w, h);
        canvas.toBlob((blob) => {
          if (blob) { const u = URL.createObjectURL(blob); triggerDownload(u, 'chart.png'); URL.revokeObjectURL(u); }
        });
      }
      URL.revokeObjectURL(svgUrl);
    };
    img.src = svgUrl;
  };

  const openSaveDialog = () => {
    if (!onSave || saved) return;
    const defaultTitle = typeof (spec as any)?.title === 'string' ? (spec as any).title : '';
    setPendingTitle(defaultTitle);
    setSaveDialogOpen(true);
  };

  const confirmSave = async () => {
    if (!onSave || saved || busy) return;
    setBusy(true);
    try { await onSave(pendingTitle.trim()); }
    finally { setBusy(false); setSaveDialogOpen(false); setMenuOpen(false); }
  };

  // react-vega's `width:"container"` is unreliable inside a CSS grid (it measures
  // before layout and stays 0 → blank chart). Measure the real width ourselves and
  // feed an explicit pixel width instead.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () => setWidth(Math.max(0, Math.floor(el.clientWidth)));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { spec, error } = useMemo(() => {
    try {
      const parsed = JSON.parse(specJson);
      if (!parsed || typeof parsed !== 'object') {
        return { spec: null, error: 'Vega-Lite spec must be a JSON object' };
      }
      const mark = typeof parsed.mark === 'string' ? parsed.mark : parsed.mark?.type;
      if (mark === 'arc') {
        // Arc/pie: fill the cell (up to a cap) so the donut is large and the legend fits.
        if (parsed.width === undefined) parsed.width = Math.min(width || 360, 460);
        if (parsed.height === undefined) parsed.height = 320;
      } else {
        // Fill the measured container width (capped so a full-row chart isn't huge).
        if (parsed.width === undefined) parsed.width = Math.min(width || 600, 900);
        if (parsed.height === undefined) parsed.height = 340;
      }
      // 'fit' makes the WHOLE chart (plot + axes + legend + title) fit the given width/height,
      // so nothing overflows or gets clipped in a narrow dashboard cell.
      if (parsed.autosize === undefined) parsed.autosize = { type: 'fit', contains: 'padding' };
      return { spec: parsed, error: null };
    } catch (e: any) {
      return { spec: null, error: e?.message || 'Invalid Vega-Lite spec JSON' };
    }
  }, [specJson, width]);

  if (error) {
    return (
      <div className="my-3 rounded-lg border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950 p-3">
        <p className="text-sm text-red-700 dark:text-red-300 font-medium mb-1">
          Chart spec parse error
        </p>
        <p className="text-xs text-red-600 dark:text-red-400 font-mono">{error}</p>
      </div>
    );
  }

  return (
    <div className="card" style={{ position: 'relative', margin: '16px 0', padding: 14, overflowX: 'auto' }}>
      {/* one menu for everything: Save to dashboard + export (replaces the separate Save + vega "…") */}
      <div style={{ position: 'absolute', top: 12, right: 12, zIndex: 3 }}>
        {menuOpen && <div onClick={() => setMenuOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 2 }} />}
        <button
          type="button"
          onClick={() => setMenuOpen((o) => !o)}
          className="focusable"
          title="Chart options"
          style={{ width: 30, height: 30, borderRadius: 8, display: 'grid', placeItems: 'center', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text-soft)', cursor: 'pointer' }}
        >
          <Icons.Dots size={16} />
        </button>
        {menuOpen && (
          <div className="card pop-shadow" style={{ position: 'absolute', top: 'calc(100% + 6px)', right: 0, zIndex: 3, width: 220, borderRadius: 'var(--r)', padding: 6 }}>
            {saveDialogOpen ? (
              <div style={{ padding: '8px 6px 4px' }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '.05em' }}>Chart name</div>
                <input
                  autoFocus
                  className="field focusable"
                  value={pendingTitle}
                  onChange={(e) => setPendingTitle(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') void confirmSave(); if (e.key === 'Escape') { setSaveDialogOpen(false); setMenuOpen(false); } }}
                  placeholder="Enter chart name…"
                  style={{ width: '100%', fontSize: 13.5, marginBottom: 8 }}
                />
                <div style={{ display: 'flex', gap: 6 }}>
                  <button type="button" onClick={() => { setSaveDialogOpen(false); setMenuOpen(false); }} className="btn btn-outline focusable" style={{ flex: 1, fontSize: 13, padding: '6px 0' }}>Cancel</button>
                  <button type="button" onClick={() => void confirmSave()} disabled={busy} className="btn btn-primary focusable" style={{ flex: 1, fontSize: 13, padding: '6px 0' }}>{busy ? 'Saving…' : 'Save'}</button>
                </div>
              </div>
            ) : (
              <>
                {onSave && (
                  <button type="button" onClick={openSaveDialog} disabled={saved} className="focusable"
                    style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '9px 10px', borderRadius: 'var(--r-sm)', border: 'none', background: 'transparent', textAlign: 'left', fontSize: 13.5, fontWeight: 600, cursor: saved ? 'default' : 'pointer', color: saved ? 'var(--text-muted)' : 'var(--text)' }}>
                    {saved ? <><Icons.Check size={16} /> Saved to dashboard</> : <><Icons.Plus size={16} /> Save to dashboard</>}
                  </button>
                )}
                <button type="button" onClick={() => void download('png')} className="focusable"
                  style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '9px 10px', borderRadius: 'var(--r-sm)', border: 'none', background: 'transparent', textAlign: 'left', fontSize: 13.5, fontWeight: 600, cursor: 'pointer', color: 'var(--text)' }}>
                  <Icons.Download size={16} /> Download PNG
                </button>
                <button type="button" onClick={() => void download('svg')} className="focusable"
                  style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '9px 10px', borderRadius: 'var(--r-sm)', border: 'none', background: 'transparent', textAlign: 'left', fontSize: 13.5, fontWeight: 600, cursor: 'pointer', color: 'var(--text)' }}>
                  <Icons.Download size={16} /> Download SVG
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {editableTitle !== undefined && (
        <div style={{ marginBottom: 6, paddingRight: 40 }}>
          {titleEditing ? (
            <input
              autoFocus
              className="field focusable"
              value={titleValue}
              onChange={(e) => setTitleValue(e.target.value)}
              onBlur={() => { setTitleEditing(false); onTitleSave?.(titleValue.trim() || editableTitle); }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { setTitleEditing(false); onTitleSave?.(titleValue.trim() || editableTitle); }
                if (e.key === 'Escape') { setTitleEditing(false); setTitleValue(editableTitle); }
              }}
              style={{ fontSize: 20, fontWeight: 700, padding: '2px 8px', width: 'auto', minWidth: 120, maxWidth: '100%' }}
            />
          ) : (
            <button
              type="button"
              onClick={() => { setTitleValue(editableTitle); setTitleEditing(true); }}
              title="Click to edit title"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'transparent', border: 'none', cursor: 'text', padding: '3px 4px', borderRadius: 'var(--r-sm)', color: 'inherit' }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
            >
              <span style={{ fontSize: 20, fontWeight: 700 }}>{editableTitle || 'Untitled chart'}</span>
              <Icons.Pencil size={12} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
            </button>
          )}
        </div>
      )}

      <div ref={wrapRef} style={{ width: '100%' }}>
        {width > 0 && (
          <VegaEmbed
            spec={spec as any}
            options={{
              mode: 'vega-lite',
              actions: false,   // we provide our own menu (Save + export)
              renderer: 'svg',
              tooltip: { theme: theme === 'dark' ? 'dark' : 'light' },
              config: config as any,
            }}
          />
        )}
      </div>
    </div>
  );
}
