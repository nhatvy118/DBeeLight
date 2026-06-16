/**
 * Tool-event readers — the single source of truth for turning backend
 * `tool_events` into UI data. Replaces the old text-marker parsing
 * (excelExportMarkers / sessionFileMarkers): the orchestrator backend emits
 * structured events, so the frontend never has to scrape `[..._START]` markers
 * out of message text anymore.
 *
 * Event contract (each event = { tool, type, payload }):
 *   - SQL preview:   tool "execute_query", payload { sql, type_sql?, explain?, mutation_preview_markdown? }
 *   - SQL executed:  type "sql_execution"
 *   - Schema editor: tool "show_create_table_schema", type "schema_preview",
 *                    payload { tableName, primaryKey, columns: [{ variable, type }] }
 *   - File export:   type "file_export", payload { filename, base64? | sessionFileId?, rowCount?, tableName? }
 *   - Session files: type "session_file", payload { files: [{ name, fileId? }] }  (attached to the user turn)
 */
import type { ToolEvent } from '../services/api';
import type { ExportData, SchemaPreviewData } from '../components/chat/MessageList';

export type SqlPreviewData = {
  sql: string;
  explain?: string;
  type_sql?: string;
  mutationPreviewMarkdown?: string | null;
};

export type SessionFileAttachment = { name: string; fileId?: string };

const payloadOf = (e?: ToolEvent): Record<string, unknown> | undefined =>
  (e?.payload as Record<string, unknown> | undefined) ?? undefined;

const str = (v: unknown): string | undefined =>
  typeof v === 'string' && v.trim().length > 0 ? v.trim() : undefined;

const firstStr = (p: Record<string, unknown>, ...keys: string[]): string | undefined => {
  for (const k of keys) {
    const s = str(p[k]);
    if (s) return s;
  }
  return undefined;
};

// ---------------------------------------------------------------- SQL preview

/** Structured SQL from `tool_events` (tool `execute_query`; payload: sql, explain, type_sql). */
export function readSqlPreview(events?: ToolEvent[]): SqlPreviewData | null {
  if (!Array.isArray(events)) return null;
  const sqlPayloadEvents = events.filter((e) => {
    if (e?.type === 'sql_execution') return false;
    if (e?.tool && e.tool !== 'execute_query') return false;
    const p = payloadOf(e);
    return !!p && typeof p.sql === 'string' && (p.sql as string).trim().length > 0;
  });
  const withTypeSql = sqlPayloadEvents.find((e) => str(payloadOf(e)?.type_sql));
  const chosen = withTypeSql ?? sqlPayloadEvents[0];
  const p = payloadOf(chosen);
  if (!p) return null;
  const sql = str(p.sql);
  if (!sql) return null;
  const explain = firstStr(p, 'explain', 'explain_summary');
  const type_sql = str(p.type_sql);
  const mutationPreviewMarkdown =
    firstStr(p, 'mutation_preview_markdown', 'mutationPreviewMarkdown') ?? null;
  return { sql, explain, type_sql, mutationPreviewMarkdown };
}

/** True once the SQL has actually run (server emits a `sql_execution` event). */
export function isSqlExecuted(events?: ToolEvent[]): boolean {
  return Array.isArray(events) && events.some((e) => e?.type === 'sql_execution');
}

// ------------------------------------------------------------- schema preview

export function readSchemaPreview(events?: ToolEvent[]): SchemaPreviewData | null {
  if (!Array.isArray(events)) return null;
  const e = events.find(
    (ev) => ev?.tool === 'show_create_table_schema' && ev?.type === 'schema_preview' && ev?.payload,
  );
  const p = payloadOf(e);
  if (!p) return null;
  const tableName = firstStr(p, 'tableName', 'table_name');
  const primaryKey = firstStr(p, 'primaryKey', 'primary_key') ?? null;
  const columnsRaw = Array.isArray(p.columns) ? (p.columns as Record<string, unknown>[]) : [];
  const columns = columnsRaw
    .map((c) => ({ variable: str(c?.variable), type: str(c?.type) }))
    .filter((c): c is { variable: string; type: string } => !!c.variable && !!c.type);
  if (!tableName || columns.length === 0) return null;
  return { tableName, primaryKey, columns };
}

// --------------------------------------------------------------- file export

/** Excel/file download offered by the assistant (event type `file_export`). */
export function readFileExport(events?: ToolEvent[]): ExportData | null {
  if (!Array.isArray(events)) return null;
  const e = events.find((ev) => ev?.type === 'file_export' && ev?.payload);
  const p = payloadOf(e);
  if (!p) return null;
  const filename = firstStr(p, 'filename', 'fileName', 'file_name');
  const sessionFileId = firstStr(p, 'sessionFileId', 'session_file_id', 'fileId', 'file_id');
  const base64 = str(p.base64);
  const tableName = firstStr(p, 'tableName', 'table_name');
  const rcRaw = p.rowCount ?? p.row_count;
  const rowCount =
    typeof rcRaw === 'number' ? rcRaw : typeof rcRaw === 'string' ? parseInt(rcRaw, 10) || 0 : 0;
  if (!filename && !sessionFileId && !base64) return null;
  return { filename, base64, sessionFileId, rowCount, tableName };
}

// --------------------------------------------------------------------- charts

/** Validate that a string is parseable JSON; return it as-is, or null. The chart
 * tool emits a clean Vega-Lite spec (json.dumps) in payload.spec — no markers. */
function asJsonSpec(raw: string): string | null {
  try {
    JSON.parse(raw);
    return raw;
  } catch {
    return null;
  }
}

/** Vega-Lite chart spec(s) from `tool_events` — detected by event type (`chart`)
 * / tool name (`generate_chart`), never by scraping message text. Returns one
 * spec JSON string per chart, in order (multiple charts → a small dashboard). */
export function readCharts(events?: ToolEvent[]): string[] {
  if (!Array.isArray(events)) return [];
  const specs: string[] = [];
  for (const e of events) {
    if (e?.type !== 'chart' && e?.tool !== 'generate_chart') continue;
    const raw = str(payloadOf(e)?.spec);
    const spec = raw ? asJsonSpec(raw) : null;
    if (spec) specs.push(spec);
  }
  return specs;
}

// ----------------------------------------------------- session file attachments

/** Files attached to a user turn (event type `session_file`). */
export function readSessionFiles(events?: ToolEvent[]): SessionFileAttachment[] | undefined {
  if (!Array.isArray(events)) return undefined;
  const out: SessionFileAttachment[] = [];
  for (const e of events) {
    if (e?.type !== 'session_file') continue;
    const p = payloadOf(e);
    if (!p) continue;
    const files = Array.isArray(p.files) ? (p.files as Record<string, unknown>[]) : [p];
    for (const f of files) {
      const name = firstStr(f, 'name', 'filename', 'file_name');
      const fileId = firstStr(f, 'fileId', 'file_id', 'id');
      if (name) out.push({ name, fileId });
    }
  }
  return out.length > 0 ? out : undefined;
}

// --------------------------------------------------------------- download util

/** Saves an `.xlsx` from an inline base64 export payload (browser only). */
export function triggerExcelDownload(data: ExportData): void {
  const rawB64 = data.base64?.trim();
  const filename = data.filename?.trim() || 'export.xlsx';
  if (!rawB64) throw new Error('No file data in export payload');
  const byteCharacters = atob(rawB64);
  const byteNumbers = new Array(byteCharacters.length);
  for (let i = 0; i < byteCharacters.length; i++) {
    byteNumbers[i] = byteCharacters.charCodeAt(i);
  }
  const byteArray = new Uint8Array(byteNumbers);
  const blob = new Blob([byteArray], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  a.remove();
}
