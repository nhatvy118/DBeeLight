import { useState } from 'react';
import ChatMessage from './ChatMessage';
import VegaLiteChart from './VegaLiteChart';
import { ResultTableCard, type TableData } from './RichResponse';
import type { ChartRecipe } from '../../services/api';

/** Pull the saveable chart recipe (sql + mark + encoding) out of a spec's usermeta.source. */
function recipeFromSpec(specJson: string): ChartRecipe | null {
  try {
    const s = JSON.parse(specJson);
    const src = s?.usermeta?.source;
    if (!src?.sql || !src?.mark || !src?.encoding) return null;
    return {
      title: typeof s?.title === 'string' ? s.title : undefined,
      sql: src.sql, mark: src.mark, encoding: src.encoding,
      transform: src.transform, layout: s?.usermeta?.layout ?? null,
    };
  } catch {
    return null;
  }
}
import { Icons, BeeBadge } from '../../icons';

// Logical column types — keep in sync with backend LOGICAL_TYPES
// (app/agent/graph/create_table_workflow.py). The server maps each to the concrete
// per-engine type at build time, so the editor stays engine-agnostic.
const SQL_TYPE_OPTIONS = [
  'integer',
  'bigint',
  'smallint',
  'text',
  'varchar(255)',
  'boolean',
  'real',
  'double',
  'decimal(10,2)',
  'date',
  'time',
  'timestamp',
  'json',
  'uuid',
  'blob',
];

// Backend/LLM-provided types are case-insensitive (e.g. "text", "bigserial") — match
// them to the preset list regardless of case instead of always falling to "Custom type…".
const matchSqlTypeOption = (type: string): string | undefined =>
  SQL_TYPE_OPTIONS.find((t) => t.toLowerCase() === (type || '').trim().toLowerCase());

// Reserved SQL keywords that can't be a table/column name — mirrors the backend guard
// (_RESERVED_KEYWORDS in create_table_workflow.py) so the editor flags it instantly
// instead of waiting for a round-trip rejection.
const RESERVED_KEYWORDS = new Set([
  'ADD', 'ALL', 'ALTER', 'AND', 'ANY', 'AS', 'ASC', 'AUTHORIZATION', 'BEGIN', 'BETWEEN',
  'BINARY', 'BOTH', 'BY', 'CASE', 'CAST', 'CHECK', 'COLLATE', 'COLUMN', 'COMMIT',
  'CONSTRAINT', 'CREATE', 'CROSS', 'CURRENT', 'CURRENT_DATE', 'CURRENT_TIME',
  'CURRENT_TIMESTAMP', 'CURRENT_USER', 'DATABASE', 'DEFAULT', 'DEFERRABLE', 'DELETE',
  'DESC', 'DISTINCT', 'DO', 'DROP', 'ELSE', 'END', 'EXCEPT', 'EXISTS', 'FALSE', 'FETCH',
  'FOR', 'FOREIGN', 'FROM', 'FULL', 'GRANT', 'GROUP', 'HAVING', 'IN', 'INDEX', 'INNER',
  'INSERT', 'INTERSECT', 'INTO', 'IS', 'JOIN', 'LEADING', 'LEFT', 'LIKE', 'LIMIT',
  'LOCALTIME', 'LOCALTIMESTAMP', 'NATURAL', 'NOT', 'NULL', 'OFFSET', 'ON', 'ONLY', 'OR',
  'ORDER', 'OUTER', 'OVER', 'PRIMARY', 'REFERENCES', 'RETURNING', 'RIGHT', 'ROLLBACK',
  'SELECT', 'SESSION_USER', 'SET', 'SOME', 'TABLE', 'THEN', 'TO', 'TRAILING',
  'TRANSACTION', 'TRIGGER', 'TRUE', 'UNION', 'UNIQUE', 'UPDATE', 'USER', 'USING',
  'VALUES', 'VIEW', 'WHEN', 'WHERE', 'WINDOW', 'WITH',
]);

const isReservedKeyword = (name: string): boolean =>
  RESERVED_KEYWORDS.has((name || '').trim().toUpperCase());

export type ExportData = {
  base64?: string;
  filename?: string;
  rowCount?: number;
  tableName?: string; // For backward compatibility
  /** Server-persisted export (same storage tree as session imports). */
  sessionFileId?: string;
};

export type SchemaPreviewColumn = {
  variable: string;
  type: string;
  notNull?: boolean;
  unique?: boolean;
  primaryKey?: boolean;
  defaultValue?: string;
  description?: string;
  enumValues?: string[];
  showOptions?: boolean;
};

export type SchemaPreviewData = {
  tableName: string;
  tableDescription?: string;
  primaryKey?: string | null;
  columns: SchemaPreviewColumn[];
  actionId?: string;
};

export type UiAttachment = {
  /** Display name shown to the user (original filename). */
  name: string;
  /** Session file id when the upload is stored server-side (e.g. for RAG). */
  fileId?: string;
};

export type UiMessage = {
  text: string;
  isUser: boolean;
  /** File(s) the user attached when sending this turn — rendered as a chip
   *  above the message bubble, ChatGPT-style. */
  attachments?: UiAttachment[];
  sqlToExecute?: string | null;
  sqlActionId?: string;
  sqlActionState?: 'pending' | 'running' | 'executed' | 'failed' | 'cancelled';
  exportToExcel?: ExportData | null;
  exportCreatedAt?: number;
  exportDownloadedAt?: number;
  /** True when the download window has closed (user sent more messages without downloading). Button shows but is disabled. */
  exportDisabled?: boolean;
  schemaPreview?: SchemaPreviewData | null;
  schemaLocked?: boolean;
  /** Locked because the action was cancelled (vs confirmed/created) — drives the header label. */
  schemaCancelled?: boolean;
  /** Assistant message is waiting on LangGraph ``interrupt()`` (schema or SQL gate). */
  workflowResumePending?: boolean;
  /** True for messages loaded from saved history — skips the typing animation. */
  historical?: boolean;
  /** Vega-Lite chart spec JSON strings emitted by the chart agent (from tool_events).
   *  Multiple specs render as a responsive grid (a mini dashboard). */
  charts?: string[];
  /** Structured read-only SELECT result (from a `query_result` event) — rendered as a table
   *  card by the frontend (the server ships {columns, rows}, never markdown). */
  queryResult?: TableData | null;
  /** Structured preview of the rows an UPDATE/DELETE would affect (from the `sql_preview`
   *  event) — rendered as a table while the action is pending. */
  mutationPreview?: TableData | null;
};

type MessageListProps = {
  messages: UiMessage[];
  onExecuteSql?: (aiIndex: number) => void;
  onCancelSql?: (aiIndex: number) => void;
  onExportFile?: (aiIndex: number) => void | Promise<void>;
  onSchemaTypeChange?: (aiIndex: number, colIdx: number, nextType: string) => void;
  onSchemaVariableChange?: (aiIndex: number, colIdx: number, name: string) => void;
  onSchemaColumnDescChange?: (aiIndex: number, colIdx: number, value: string) => void;
  onSchemaColumnEnumChange?: (aiIndex: number, colIdx: number, value: string) => void;
  onSchemaTableNameChange?: (aiIndex: number, name: string) => void;
  onSchemaTableDescChange?: (aiIndex: number, value: string) => void;
  onToggleSchemaOptions?: (aiIndex: number, colIdx: number) => void;
  onSchemaOptionChange?: (
    aiIndex: number,
    colIdx: number,
    option: 'notNull' | 'unique' | 'primaryKey' | 'defaultValue',
    value: boolean | string
  ) => void;
  onSchemaAddColumn?: (aiIndex: number) => void;
  onSchemaRemoveColumn?: (aiIndex: number, colIdx: number) => void;
  onConfirmSchema?: (aiIndex: number) => void;
  onAssistantTypingChange?: (isTyping: boolean) => void;
  typingStopSignal?: number;
  /** Save a chart to the current project's dashboard (resolves true on success). Omitted
   *  when not inside a project. */
  onSaveChart?: (recipe: ChartRecipe) => void | Promise<boolean>;
};

export default function MessageList({
  messages,
  onExecuteSql,
  onCancelSql,
  onExportFile,
  onSchemaTypeChange,
  onSchemaVariableChange,
  onSchemaColumnDescChange,
  onSchemaColumnEnumChange,
  onSchemaTableNameChange,
  onSchemaTableDescChange,
  onToggleSchemaOptions,
  onSchemaOptionChange,
  onSchemaAddColumn,
  onSchemaRemoveColumn,
  onConfirmSchema,
  onAssistantTypingChange,
  typingStopSignal = 0,
  onSaveChart,
}: MessageListProps) {
  const [exportingIndex, setExportingIndex] = useState<number | null>(null);
  // Last assistant message still being typed out → its action buttons (Cancel/Execute,
  // Confirm & create table) stay hidden until the text finishes revealing.
  const [lastMessageTyping, setLastMessageTyping] = useState(false);
  const handleLastTypingChange = (typing: boolean) => {
    setLastMessageTyping(typing);
    onAssistantTypingChange?.(typing);
  };
  // Charts saved to the dashboard this session → their button shows "Saved" (prevents
  // re-saving; the backend also dedupes by project + sql + mark).
  const [savedChartKeys, setSavedChartKeys] = useState<Set<string>>(new Set());
  // Which column's description is open in the inline editor, keyed by message + column.
  // Progressive disclosure: descriptions show as chips and expand on click.
  const [descEditor, setDescEditor] = useState<{ msg: number; col: number } | null>(null);

  const runFileDownload = async (idx: number) => {
    if (!onExportFile || exportingIndex !== null) return;
    setExportingIndex(idx);
    try {
      await Promise.resolve(onExportFile(idx));
    } finally {
      setExportingIndex(null);
    }
  };

  if (messages.length === 0) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 26 }}>
      {messages.map((msg, index) => {
        // The last assistant message is still being typed out → action buttons
        // (Cancel/Execute, Confirm & create table) stay hidden/disabled until done.
        const isLastTyping = !msg.isUser && index === messages.length - 1 && lastMessageTyping;
        const turnBody = (
          <>
          {/* filename alone is enough: ephemeral exports (stateless excel) persist without
              base64/sessionFileId — the blob is fetched from this device's IndexedDB. */}
          {!msg.isUser && msg.exportToExcel?.filename ? (
            <div style={{ display: 'flex', justifyContent: 'flex-start', width: '100%', marginBottom: 8 }}>
              <div style={{ width: '100%', maxWidth: 320, display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
                <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '11px 14px' }} title={msg.exportToExcel.filename}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                    <span style={{ width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center', background: 'var(--green-soft)', color: 'var(--green-ink)', flexShrink: 0 }}>
                      <Icons.Table size={17} />
                    </span>
                    <span style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>
                      {msg.exportToExcel.filename}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', width: '100%', borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                    <button
                      type="button"
                      disabled={!onExportFile || exportingIndex === index || msg.exportDisabled}
                      onClick={() => void runFileDownload(index)}
                      className={msg.exportDisabled ? undefined : 'btn btn-outline'}
                      title={msg.exportDisabled ? 'Download window has expired' : undefined}
                      style={{
                        padding: '6px 14px', fontSize: 13,
                        ...(msg.exportDisabled ? {
                          display: 'inline-flex', alignItems: 'center', gap: 6,
                          borderRadius: 'var(--r-sm)', border: '1px solid var(--border)',
                          background: 'var(--surface)', color: 'var(--text-muted)',
                          opacity: 0.5, cursor: 'not-allowed', pointerEvents: 'none',
                        } : {}),
                      }}
                    >
                      <Icons.Download size={15} />
                      {exportingIndex === index ? '…' : 'Download'}
                    </button>
                  </div>
                </div>
                {typeof msg.exportToExcel.rowCount === 'number' && msg.exportToExcel.rowCount > 0 ? (
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', paddingLeft: 4 }}>
                    {msg.exportToExcel.rowCount.toLocaleString()} rows
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}
          <ChatMessage
            message={msg.text}
            isUser={msg.isUser}
            attachments={msg.attachments}
            enableTyping={!msg.historical}
            sqlExecuted={!msg.isUser && msg.sqlActionState === 'executed'}
            sqlFailed={!msg.isUser && msg.sqlActionState === 'failed'}
            onTypingStateChange={
              !msg.isUser && index === messages.length - 1 ? handleLastTypingChange : undefined
            }
            typingStopSignal={!msg.isUser && index === messages.length - 1 ? typingStopSignal : 0}
          />
          {!msg.isUser && msg.queryResult && (msg.queryResult.columns.length > 0 || msg.queryResult.rows.length > 0) && (
            <ResultTableCard data={msg.queryResult} />
          )}
          {!msg.isUser && msg.mutationPreview && msg.sqlActionState === 'pending' &&
            (msg.mutationPreview.columns.length > 0 || msg.mutationPreview.rows.length > 0) && (
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                  Rows that would be affected
                </div>
                <ResultTableCard data={msg.mutationPreview} />
              </div>
            )}
          {!msg.isUser && msg.charts && msg.charts.length > 0 && (() => {
            // Read the per-chart layout hint (spec.usermeta.layout, set by the chart tool).
            // 'full' spans the whole row; otherwise a chart takes one auto-fit column.
            const items = msg.charts.map((spec) => {
              let layout: string | undefined;
              try { layout = (JSON.parse(spec)?.usermeta?.layout) as string | undefined; } catch { /* keep spec */ }
              return { spec, layout };
            });
            const multi = items.length > 1;
            return (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: multi ? 'repeat(auto-fit, minmax(340px, 1fr))' : '1fr',
                  gap: 12,
                  marginTop: 8,
                }}
              >
                {items.map(({ spec, layout }, ci) => {
                  const full = !multi || layout !== 'half';
                  const recipe = onSaveChart ? recipeFromSpec(spec) : null;
                  const savedKey = recipe ? `${recipe.sql}|${recipe.mark}` : '';
                  const isSaved = !!savedKey && savedChartKeys.has(savedKey);
                  return (
                    <div key={ci} style={{ gridColumn: full ? '1 / -1' : 'auto', minWidth: 0, position: 'relative' }}>
                      <VegaLiteChart
                        specJson={spec}
                        saved={isSaved}
                        onSave={recipe ? async (title: string) => {
                          const ok = await onSaveChart?.({ ...recipe, title: title || recipe.title });
                          if (ok) setSavedChartKeys((s) => new Set(s).add(savedKey));
                          return ok;
                        } : undefined}
                      />
                    </div>
                  );
                })}
              </div>
            );
          })()}
          {!msg.isUser && msg.schemaPreview && (() => {
            const sp = msg.schemaPreview;
            const locked = !!msg.schemaLocked;
            const cancelled = !!msg.schemaCancelled;   // locked, but it was cancelled (not created)
            // Progress meter: the table description + every column description must be filled.
            const total = sp.columns.length + 1;
            const done = sp.columns.filter((c) => (c.description || '').trim()).length + ((sp.tableDescription || '').trim() ? 1 : 0);
            const allDone = done >= total;
            const tableDescOk = (sp.tableDescription || '').trim().length > 0;
            // Reserved-keyword names (SELECT, ORDER, …) are rejected by the DB — flag them
            // in the editor and block confirm so the user fixes it without a round-trip.
            const tableNameReserved = isReservedKeyword(sp.tableName);
            const anyColNameReserved = sp.columns.some((c) => isReservedKeyword(c.variable));
            const nameOk = !tableNameReserved && !anyColNameReserved;

            return (
            <div className="card" style={{ overflow: 'hidden', marginTop: 14, marginBottom: 8, borderColor: locked && !cancelled ? 'var(--green-soft)' : 'var(--border)' }}>
              {/* Header — title + editable table name */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '11px 16px', borderBottom: '1px solid var(--border)', background: locked && !cancelled ? 'var(--green-soft)' : 'var(--surface-2)' }}>
                {cancelled ? <Icons.Close size={16} style={{ color: 'var(--text-muted)' }} /> : locked ? <Icons.Check size={16} style={{ color: 'var(--green-ink)' }} /> : <Icons.Table size={16} style={{ color: 'var(--text-soft)' }} />}
                <span style={{ fontSize: 13.5, fontWeight: 700, color: cancelled ? 'var(--text-muted)' : locked ? 'var(--green-ink)' : 'var(--text)' }}>
                  {cancelled ? 'Schema cancelled' : locked ? 'Schema confirmed' : 'Proposed table'}
                </span>
                {locked ? (
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-soft)', background: 'var(--surface)', padding: '2px 8px', borderRadius: 6, border: '1px solid var(--border)' }}>
                    {sp.tableName}
                  </span>
                ) : (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, position: 'relative' }}>
                    <input
                      type="text"
                      className="field focusable"
                      style={{ fontFamily: 'var(--font-mono)', fontSize: 13, padding: '3px 26px 3px 8px', borderRadius: 6, maxWidth: 220,
                        border: tableNameReserved ? '1px solid var(--danger)' : undefined }}
                      value={sp.tableName}
                      onChange={(e) => onSchemaTableNameChange?.(index, e.target.value)}
                      placeholder="table name"
                      title={tableNameReserved ? 'Reserved SQL keyword — pick another name' : undefined}
                    />
                    <Icons.Pencil size={13} style={{ position: 'absolute', right: 8, color: 'var(--text-faint)', pointerEvents: 'none' }} />
                  </span>
                )}
                {/* Progress meter — "X/Y described" */}
                {!locked && (
                  <span
                    style={{
                      marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 7,
                      padding: '4px 11px', borderRadius: 999, fontSize: 12, fontWeight: 600,
                      background: allDone ? 'var(--green-soft)' : 'var(--honey-soft)',
                      color: allDone ? 'var(--green-ink)' : 'var(--honey-ink)',
                      border: `1px solid ${allDone ? 'transparent' : 'var(--honey-soft-2)'}`,
                    }}
                    title="Descriptions completed"
                  >
                    <span style={{ width: 7, height: 7, borderRadius: 999, background: allDone ? 'var(--green)' : 'var(--honey-strong)' }} />
                    {done}/{total} described
                  </span>
                )}
              </div>

              {/* Table description — labeled textarea */}
              <div style={{ padding: '12px 16px 4px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, fontSize: 12, fontWeight: 600, color: tableDescOk || locked ? 'var(--text-soft)' : 'var(--honey-ink)' }}>
                  {tableDescOk || locked
                    ? <Icons.Check size={13} style={{ color: 'var(--green-ink)' }} />
                    : <Icons.Info size={13} />}
                  Table description{!locked && ' — required'}
                </div>
                {locked ? (
                  <div style={{ fontSize: 12.5, color: 'var(--text-muted)', lineHeight: 1.5 }}>{sp.tableDescription || '—'}</div>
                ) : (
                  <textarea
                    className="field focusable"
                    rows={2}
                    style={{ width: '100%', fontSize: 12.5, padding: '8px 11px', borderRadius: 8, lineHeight: 1.5,
                      border: `1px solid ${tableDescOk ? 'var(--border)' : 'var(--danger)'}` }}
                    value={sp.tableDescription || ''}
                    onChange={(e) => onSchemaTableDescChange?.(index, e.target.value)}
                    placeholder="What does this table store? e.g. “One row per sales transaction.”"
                  />
                )}
              </div>

              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Column</th>
                      <th>Type</th>
                      <th>Description</th>
                      <th style={{ width: 76 }}></th>
                    </tr>
                  </thead>
                  {sp.columns.map((col, colIdx) => {
                    const hasDesc = (col.description || '').trim().length > 0;
                    const editing = !locked && descEditor?.msg === index && descEditor?.col === colIdx;
                    const colNameReserved = isReservedKeyword(col.variable);
                    return (
                    <tbody key={colIdx}>
                      <tr>
                        <td>
                          {locked ? (
                            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{col.variable}</span>
                          ) : (
                            <input
                              type="text"
                              className="field focusable"
                              style={{ padding: '7px 10px', fontSize: 13, fontFamily: 'var(--font-mono)', fontWeight: 600, maxWidth: 180,
                                border: colNameReserved ? '1px solid var(--danger)' : undefined }}
                              value={col.variable}
                              onChange={(e) => onSchemaVariableChange?.(index, colIdx, e.target.value)}
                              placeholder="column_name"
                              title={colNameReserved ? 'Reserved SQL keyword — pick another name' : undefined}
                            />
                          )}
                        </td>
                        <td>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            <select
                              className="field focusable"
                              style={{ padding: '7px 10px', fontSize: 13, fontFamily: 'var(--font-mono)', maxWidth: 160 }}
                              value={matchSqlTypeOption(col.type) ?? '__custom__'}
                              disabled={locked}
                              onChange={(e) => {
                                const v = e.target.value;
                                onSchemaTypeChange?.(index, colIdx, v !== '__custom__' ? v : 'CUSTOM_TYPE');
                              }}
                            >
                              {SQL_TYPE_OPTIONS.map((t) => (
                                <option key={t} value={t}>{t}</option>
                              ))}
                              <option value="__custom__">Custom type…</option>
                            </select>
                            {!matchSqlTypeOption(col.type) && (
                              <input
                                type="text"
                                className="field focusable"
                                style={{ padding: '7px 10px', fontSize: 13, fontFamily: 'var(--font-mono)', maxWidth: 160 }}
                                value={col.type}
                                disabled={locked}
                                onChange={(e) => onSchemaTypeChange?.(index, colIdx, e.target.value)}
                                placeholder="Custom type"
                              />
                            )}
                          </div>
                        </td>
                        {/* Description — chip that expands into an inline editor */}
                        <td>
                          {locked ? (
                            <span style={{ fontSize: 12, color: hasDesc ? 'var(--text-muted)' : 'var(--text-faint)' }}>
                              {col.description || '—'}
                            </span>
                          ) : (
                            <button
                              type="button"
                              className="focusable"
                              onClick={() => setDescEditor(editing ? null : { msg: index, col: colIdx })}
                              title={hasDesc ? 'Edit description' : 'Add description'}
                              style={{
                                display: 'inline-flex', alignItems: 'center', gap: 6, maxWidth: 260,
                                padding: '5px 11px', borderRadius: 999, fontSize: 12.5, fontWeight: 500,
                                cursor: 'pointer', textAlign: 'left',
                                background: hasDesc ? 'var(--surface-2)' : 'var(--honey-soft)',
                                color: hasDesc ? 'var(--text-soft)' : 'var(--honey-ink)',
                                border: hasDesc ? '1px solid var(--border)' : '1px dashed var(--honey-soft-2)',
                              }}
                            >
                              {hasDesc ? <Icons.Check size={13} style={{ flexShrink: 0, color: 'var(--green-ink)' }} /> : <Icons.Plus size={13} style={{ flexShrink: 0 }} />}
                              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {hasDesc ? col.description : 'Add description'}
                              </span>
                            </button>
                          )}
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <button
                              type="button"
                              disabled={locked}
                              onClick={() => onToggleSchemaOptions?.(index, colIdx)}
                              className="focusable"
                              style={{ width: 28, height: 28, borderRadius: 7, display: 'grid', placeItems: 'center', border: '1px solid var(--border)', background: col.showOptions ? 'var(--accent-soft)' : 'var(--surface)', color: col.showOptions ? 'var(--accent-ink)' : 'var(--text-muted)' }}
                              title="Constraints"
                            >
                              <Icons.Settings size={14} />
                            </button>
                            {!locked && (
                              <button
                                type="button"
                                disabled={(sp.columns.length ?? 0) <= 1}
                                onClick={() => onSchemaRemoveColumn?.(index, colIdx)}
                                className="focusable"
                                style={{ width: 28, height: 28, borderRadius: 7, display: 'grid', placeItems: 'center', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text-muted)', cursor: (sp.columns.length ?? 0) <= 1 ? 'not-allowed' : 'pointer', opacity: (sp.columns.length ?? 0) <= 1 ? 0.4 : 1 }}
                                title="Remove column"
                              >
                                <Icons.Trash size={14} />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                      {/* Inline description editor */}
                      {editing && (
                        <tr>
                          <td colSpan={4} style={{ padding: '14px 14px 16px' }}>
                            <div style={{ background: 'var(--surface-2)', border: '1px solid var(--accent-soft-2)', borderRadius: 10, padding: '14px 16px' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8, fontSize: 12, fontWeight: 600, color: 'var(--text-soft)' }}>
                                Describe
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--accent-ink)', background: 'var(--accent-soft)', padding: '1px 7px', borderRadius: 6 }}>
                                  {col.variable || 'column'}
                                </span>
                              </div>
                              <textarea
                                autoFocus
                                className="field focusable"
                                rows={2}
                                style={{ width: '100%', fontSize: 12.5, padding: '8px 11px', borderRadius: 8, lineHeight: 1.5 }}
                                value={col.description || ''}
                                onChange={(e) => onSchemaColumnDescChange?.(index, colIdx, e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); setDescEditor(null); }
                                  if (e.key === 'Escape') setDescEditor(null);
                                }}
                                placeholder={`What does “${col.variable}” mean? e.g. its unit, source, or allowed values`}
                              />
                              <input
                                type="text"
                                className="field focusable"
                                style={{ width: '100%', fontSize: 12, padding: '7px 11px', borderRadius: 8, marginTop: 8 }}
                                value={(col.enumValues || []).join(', ')}
                                onChange={(e) => onSchemaColumnEnumChange?.(index, colIdx, e.target.value)}
                                placeholder="Allowed values (optional, comma-separated) — e.g. pending, shipped, cancelled"
                              />
                              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
                                <button
                                  type="button"
                                  onClick={() => setDescEditor(null)}
                                  className="btn btn-primary"
                                  style={{ padding: '6px 16px', fontSize: 13 }}
                                >
                                  <Icons.Check size={14} /> Done
                                </button>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                      {col.showOptions && (
                        <tr>
                          <td colSpan={4} style={{ background: 'var(--surface-2)', padding: '10px 14px' }}>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center' }}>
                              {([['notNull', 'NOT NULL'], ['unique', 'UNIQUE'], ['primaryKey', 'PRIMARY KEY']] as const).map(([k, label]) => (
                                <label key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, fontWeight: 600, color: 'var(--text-soft)', cursor: 'pointer' }}>
                                  <input
                                    type="checkbox"
                                    checked={!!col[k]}
                                    disabled={locked}
                                    onChange={(e) => onSchemaOptionChange?.(index, colIdx, k, e.target.checked)}
                                    style={{ accentColor: 'var(--accent-strong)', width: 15, height: 15 }}
                                  />
                                  {label}
                                </label>
                              ))}
                              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, fontWeight: 600, color: 'var(--text-soft)' }}>
                                DEFAULT
                                <input
                                  type="text"
                                  value={col.defaultValue || ''}
                                  disabled={locked}
                                  onChange={(e) => onSchemaOptionChange?.(index, colIdx, 'defaultValue', e.target.value)}
                                  placeholder="value"
                                  style={{ width: 110, padding: '5px 8px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', fontSize: 12.5 }}
                                />
                              </span>
                            </div>
                          </td>
                        </tr>
                      )}
                    </tbody>
                    );
                  })}
                </table>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: '11px 16px', borderTop: '1px solid var(--border)' }}>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: 12.5, color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                    <Icons.Info size={14} />
                    {locked ? `${sp.columns.length} columns · imported` : `${sp.columns.length} columns`}
                  </span>
                  {!locked && (
                    <button
                      type="button"
                      onClick={() => onSchemaAddColumn?.(index)}
                      className="focusable"
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px', fontSize: 13, fontWeight: 600, borderRadius: 7, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text-soft)', cursor: 'pointer' }}
                    >
                      <Icons.Plus size={14} /> Add column
                    </button>
                  )}
                  {!locked && !nameOk && (
                    <span style={{ fontSize: 12, color: 'var(--danger)', fontWeight: 600 }}>
                      {tableNameReserved ? 'Table name' : 'A column name'} is a reserved SQL keyword — rename it
                    </span>
                  )}
                  {!locked && nameOk && !allDone && (
                    <span style={{ fontSize: 12, color: 'var(--honey-ink)', fontWeight: 600 }}>
                      {total - done} description{total - done === 1 ? '' : 's'} left
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => onConfirmSchema?.(index)}
                  disabled={locked || isLastTyping || !allDone || !nameOk}
                  className="btn btn-primary"
                  style={{ padding: '9px 18px', fontSize: 13.5, opacity: (locked || isLastTyping || !allDone || !nameOk) ? 0.7 : 1 }}
                >
                  <Icons.Check size={15} />
                  {cancelled ? 'Cancelled' : locked ? 'Schema confirmed' : 'Confirm & create table'}
                </button>
              </div>
            </div>
            );
          })()}

          {!msg.isUser && (() => {
            const sqlAction = msg.sqlToExecute && onExecuteSql ? (() => {
                const state = msg.sqlActionState;

                // Still typing out the response → hold off on the Cancel/Execute
                // buttons until the text has fully revealed.
                if (isLastTyping) return null;

                // Running → loading dots (reference SqlPreview "running" state).
                if (state === 'running') {
                  return (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 9, fontSize: 13, fontWeight: 600, color: 'var(--text-soft)' }}>
                      <span style={{ display: 'inline-flex', gap: 4 }}>
                        {[0, 1, 2].map((i) => (
                          <span key={i} style={{ width: 6, height: 6, borderRadius: 99, background: 'var(--accent-strong)', animation: `dotPulse 1.2s ${i * 0.18}s infinite ease-in-out` }} />
                        ))}
                      </span>
                      Running…
                    </span>
                  );
                }

                // Executed → no button row; the SQL card itself turns green
                // "Query executed" (handled in ChatMessage / CodeBlockCard),
                // matching how read-only queries look.
                if (state === 'executed') return null;

                // Failed → terminal too: the workflow already ran and is consumed, so re-running
                // does nothing. The card header shows red "Query failed"; no Execute button.
                if (state === 'failed') return null;

                if (state === 'cancelled') {
                  return (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', padding: '7px 4px' }}>
                      <Icons.Close size={15} />
                      Cancelled
                    </span>
                  );
                }

                // Pending → Cancel / Execute buttons.
                return (
                  <>
                    {onCancelSql && (
                      <button
                        type="button"
                        onClick={() => void onCancelSql(index)}
                        className="btn btn-outline"
                        style={{ padding: '7px 14px', fontSize: 13 }}
                      >
                        Cancel
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => void onExecuteSql(index)}
                      className="btn btn-primary"
                      style={{ padding: '7px 16px', fontSize: 13 }}
                    >
                      <Icons.Lightning size={15} />
                      Execute
                    </button>
                  </>
                );
              })() : null;

            if (!sqlAction) return null;

            return (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 6, marginTop: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {sqlAction}
                </div>
              </div>
            );
          })()}
          </>
        );

        return (
          <div key={index} style={{ width: '100%' }}>
            {msg.isUser ? (
              turnBody
            ) : (
              <div style={{ display: 'flex', gap: 14 }}>
                <BeeBadge size={34} style={{ flexShrink: 0, marginTop: 2 }} />
                <div style={{ flex: 1, minWidth: 0 }}>{turnBody}</div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

