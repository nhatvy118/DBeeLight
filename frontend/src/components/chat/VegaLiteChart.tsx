import { useMemo } from 'react';
import { VegaEmbed } from 'react-vega';

type VegaLiteChartProps = {
  /** Raw JSON string of a Vega-Lite v5 spec, as emitted between
   * [VEGA_SPEC_START] / [VEGA_SPEC_END] markers by the chart agent. */
  specJson: string;
};

/** Renders a Vega-Lite v5 spec inline in chat. Falls back to a code-block
 * style error display when the spec is malformed. */
export default function VegaLiteChart({ specJson }: VegaLiteChartProps) {
  const { spec, error } = useMemo(() => {
    try {
      const parsed = JSON.parse(specJson);
      if (!parsed || typeof parsed !== 'object') {
        return { spec: null, error: 'Vega-Lite spec must be a JSON object' };
      }
      return { spec: parsed, error: null };
    } catch (e: any) {
      return { spec: null, error: e?.message || 'Invalid Vega-Lite spec JSON' };
    }
  }, [specJson]);

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
    <div className="my-4 not-prose rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-3 overflow-x-auto">
      <VegaEmbed
        spec={spec as any}
        options={{
          mode: 'vega-lite',
          actions: { export: true, source: false, compiled: false, editor: false },
          renderer: 'canvas',
        }}
      />
    </div>
  );
}
