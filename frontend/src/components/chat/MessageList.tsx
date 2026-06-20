import { useState } from 'react';
import ChatMessage from './ChatMessage';
import VegaLiteChart from './VegaLiteChart';
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
  showOptions?: boolean;
};

export type SchemaPreviewData = {
  tableName: string;
  primaryKey?: string | null;
  columns: SchemaPreviewColumn[];
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
  schemaPreview?: SchemaPreviewData | null;
  schemaLocked?: boolean;
  /** Assistant message is waiting on LangGraph ``interrupt()`` (schema or SQL gate). */
  workflowResumePending?: boolean;
  /** Vega-Lite chart spec JSON strings emitted by the chart agent (from tool_events).
   *  Multiple specs render as a responsive grid (a mini dashboard). */
  charts?: string[];
};

type MessageListProps = {
  messages: UiMessage[];
  onRefreshResponse?: (aiIndex: number) => void;
  onExecuteSql?: (aiIndex: number) => void;
  onCancelSql?: (aiIndex: number) => void;
  onExportFile?: (aiIndex: number) => void | Promise<void>;
  onSchemaTypeChange?: (aiIndex: number, colIdx: number, nextType: string) => void;
  onSchemaVariableChange?: (aiIndex: number, colIdx: number, name: string) => void;
  onSchemaTableNameChange?: (aiIndex: number, name: string) => void;
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
  onRefreshResponse,
  onExecuteSql,
  onCancelSql,
  onExportFile,
  onSchemaTypeChange,
  onSchemaVariableChange,
  onSchemaTableNameChange,
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
          {!msg.isUser &&
          msg.exportToExcel?.filename &&
          (msg.exportToExcel.base64 || msg.exportToExcel.sessionFileId) ? (
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
                      disabled={!onExportFile || exportingIndex === index}
                      onClick={() => void runFileDownload(index)}
                      className="btn btn-outline"
                      style={{ padding: '6px 14px', fontSize: 13 }}
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
            sqlExecuted={!msg.isUser && msg.sqlActionState === 'executed'}
            sqlFailed={!msg.isUser && msg.sqlActionState === 'failed'}
            onTypingStateChange={
              !msg.isUser && index === messages.length - 1 ? handleLastTypingChange : undefined
            }
            typingStopSignal={!msg.isUser && index === messages.length - 1 ? typingStopSignal : 0}
          />
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
                      {recipe && (
                        <button
                          type="button"
                          disabled={isSaved}
                          onClick={() => {
                            void (async () => {
                              const ok = await onSaveChart?.(recipe);
                              if (ok) setSavedChartKeys((s) => new Set(s).add(savedKey));
                            })();
                          }}
                          title={isSaved ? 'Already saved to dashboard' : 'Save to dashboard'}
                          className="btn btn-outline"
                          style={{ position: 'absolute', top: 22, right: 22, zIndex: 2, padding: '5px 10px', fontSize: 12.5 }}
                        >
                          {isSaved ? <><Icons.Check size={14} /> Saved</> : <><Icons.Plus size={14} /> Save</>}
                        </button>
                      )}
                      <VegaLiteChart specJson={spec} />
                    </div>
                  );
                })}
              </div>
            );
          })()}
          {!msg.isUser && msg.schemaPreview && (
            <div className="card" style={{ overflow: 'hidden', marginTop: 14, marginBottom: 8, borderColor: msg.schemaLocked ? 'var(--green-soft)' : 'var(--border)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '11px 16px', borderBottom: '1px solid var(--border)', background: msg.schemaLocked ? 'var(--green-soft)' : 'var(--surface-2)' }}>
                {msg.schemaLocked ? <Icons.Check size={16} style={{ color: 'var(--green-ink)' }} /> : <Icons.Table size={16} style={{ color: 'var(--text-soft)' }} />}
                <span style={{ fontSize: 13.5, fontWeight: 700, color: msg.schemaLocked ? 'var(--green-ink)' : 'var(--text)' }}>
                  {msg.schemaLocked ? 'Schema confirmed' : 'Proposed table'}
                </span>
                {msg.schemaLocked ? (
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-soft)', background: 'var(--surface)', padding: '2px 8px', borderRadius: 6, border: '1px solid var(--border)' }}>
                    {msg.schemaPreview.tableName}
                  </span>
                ) : (
                  <input
                    type="text"
                    className="field focusable"
                    style={{ fontFamily: 'var(--font-mono)', fontSize: 13, padding: '3px 8px', borderRadius: 6, maxWidth: 220 }}
                    value={msg.schemaPreview.tableName}
                    onChange={(e) => onSchemaTableNameChange?.(index, e.target.value)}
                    placeholder="table name"
                  />
                )}
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Column</th>
                      <th>Type</th>
                      <th style={{ width: 76 }}></th>
                    </tr>
                  </thead>
                  {msg.schemaPreview.columns.map((col, colIdx) => (
                    <tbody key={colIdx}>
                      <tr>
                        <td>
                          {msg.schemaLocked ? (
                            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{col.variable}</span>
                          ) : (
                            <input
                              type="text"
                              className="field focusable"
                              style={{ padding: '7px 10px', fontSize: 13, fontFamily: 'var(--font-mono)', fontWeight: 600, maxWidth: 200 }}
                              value={col.variable}
                              onChange={(e) => onSchemaVariableChange?.(index, colIdx, e.target.value)}
                              placeholder="column_name"
                            />
                          )}
                        </td>
                        <td>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            <select
                              className="field focusable"
                              style={{ padding: '7px 10px', fontSize: 13, fontFamily: 'var(--font-mono)', maxWidth: 220 }}
                              value={matchSqlTypeOption(col.type) ?? '__custom__'}
                              disabled={!!msg.schemaLocked}
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
                                style={{ padding: '7px 10px', fontSize: 13, fontFamily: 'var(--font-mono)', maxWidth: 220 }}
                                value={col.type}
                                disabled={!!msg.schemaLocked}
                                onChange={(e) => onSchemaTypeChange?.(index, colIdx, e.target.value)}
                                placeholder="Custom type"
                              />
                            )}
                          </div>
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <button
                              type="button"
                              disabled={!!msg.schemaLocked}
                              onClick={() => onToggleSchemaOptions?.(index, colIdx)}
                              className="focusable"
                              style={{ width: 28, height: 28, borderRadius: 7, display: 'grid', placeItems: 'center', border: '1px solid var(--border)', background: col.showOptions ? 'var(--accent-soft)' : 'var(--surface)', color: col.showOptions ? 'var(--accent-ink)' : 'var(--text-muted)' }}
                              title="Constraints"
                            >
                              <Icons.Settings size={14} />
                            </button>
                            {!msg.schemaLocked && (
                              <button
                                type="button"
                                disabled={(msg.schemaPreview?.columns.length ?? 0) <= 1}
                                onClick={() => onSchemaRemoveColumn?.(index, colIdx)}
                                className="focusable"
                                style={{ width: 28, height: 28, borderRadius: 7, display: 'grid', placeItems: 'center', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text-muted)', fontSize: 18, lineHeight: 1, cursor: (msg.schemaPreview?.columns.length ?? 0) <= 1 ? 'not-allowed' : 'pointer', opacity: (msg.schemaPreview?.columns.length ?? 0) <= 1 ? 0.4 : 1 }}
                                title="Remove column"
                              >
                                ×
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                      {col.showOptions && (
                        <tr>
                          <td colSpan={3} style={{ background: 'var(--surface-2)', padding: '10px 14px' }}>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center' }}>
                              {([['notNull', 'NOT NULL'], ['unique', 'UNIQUE'], ['primaryKey', 'PRIMARY KEY']] as const).map(([k, label]) => (
                                <label key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, fontWeight: 600, color: 'var(--text-soft)', cursor: 'pointer' }}>
                                  <input
                                    type="checkbox"
                                    checked={!!col[k]}
                                    disabled={!!msg.schemaLocked}
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
                                  disabled={!!msg.schemaLocked}
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
                  ))}
                </table>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: '11px 16px', borderTop: '1px solid var(--border)' }}>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: 12.5, color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                    <Icons.Info size={14} />
                    {msg.schemaLocked ? `${msg.schemaPreview.columns.length} columns · imported` : `${msg.schemaPreview.columns.length} columns`}
                  </span>
                  {!msg.schemaLocked && (
                    <button
                      type="button"
                      onClick={() => onSchemaAddColumn?.(index)}
                      className="focusable"
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px', fontSize: 13, fontWeight: 600, borderRadius: 7, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text-soft)', cursor: 'pointer' }}
                    >
                      <Icons.Plus size={14} /> Add column
                    </button>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => onConfirmSchema?.(index)}
                  disabled={!!msg.schemaLocked || isLastTyping}
                  className="btn btn-primary"
                  style={{ padding: '9px 18px', fontSize: 13.5, opacity: msg.schemaLocked || isLastTyping ? 0.7 : 1 }}
                >
                  <Icons.Check size={15} />
                  {msg.schemaLocked ? 'Schema confirmed' : 'Confirm & create table'}
                </button>
              </div>
            </div>
          )}

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

            return (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 6, marginTop: 12 }}>
                {sqlAction && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {sqlAction}
                  </div>
                )}
                {onRefreshResponse && (
                  <button
                    type="button"
                    onClick={() => void onRefreshResponse(index)}
                    className="focusable"
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, color: 'var(--text-muted)', background: 'transparent', border: 'none' }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; e.currentTarget.style.color = 'var(--text)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-muted)'; }}
                  >
                    <Icons.Refresh size={15} />
                    <span>Regenerate</span>
                  </button>
                )}
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

