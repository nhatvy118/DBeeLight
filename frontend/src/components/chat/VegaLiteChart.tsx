import { useEffect, useMemo, useRef, useState } from 'react';
import { VegaEmbed } from 'react-vega';
import { useTheme } from '../../context/ThemeContext';

type VegaLiteChartProps = {
  /** Raw JSON string of a Vega-Lite v5 spec, taken from a `generate_chart`
   * tool_event payload (detected by tool name, not message-text markers). */
  specJson: string;
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
export default function VegaLiteChart({ specJson }: VegaLiteChartProps) {
  const { theme } = useTheme();
  const config = useVegaConfig(theme);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

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
    <div className="card" style={{ margin: '16px 0', padding: 14, overflowX: 'auto' }}>
      <div ref={wrapRef} style={{ width: '100%' }}>
        {width > 0 && (
          <VegaEmbed
            spec={spec as any}
            options={{
              mode: 'vega-lite',
              actions: { export: true, source: false, compiled: false, editor: false },
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
