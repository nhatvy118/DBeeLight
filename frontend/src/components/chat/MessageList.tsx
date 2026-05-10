import { useState } from 'react';
import ChatMessage from './ChatMessage';

const SQL_TYPE_OPTIONS = [
  'INTEGER',
  'BIGINT',
  'SMALLINT',
  'SERIAL',
  'TEXT',
  'VARCHAR(50)',
  'VARCHAR(100)',
  'VARCHAR(255)',
  'BOOLEAN',
  'DATE',
  'TIMESTAMP',
  'DECIMAL(10,2)',
  'FLOAT',
  'DOUBLE',
  'JSON',
  'JSONB',
];

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
  sqlActionState?: 'pending' | 'running' | 'executed' | 'cancelled';
  exportToExcel?: ExportData | null;
  schemaPreview?: SchemaPreviewData | null;
  schemaLocked?: boolean;
  /** Assistant message is waiting on LangGraph ``interrupt()`` (schema or SQL gate). */
  workflowResumePending?: boolean;
};

type MessageListProps = {
  messages: UiMessage[];
  onRefreshResponse?: (aiIndex: number) => void;
  onExecuteSql?: (aiIndex: number) => void;
  onCancelSql?: (aiIndex: number) => void;
  onExportFile?: (aiIndex: number) => void | Promise<void>;
  onSchemaTypeChange?: (aiIndex: number, variable: string, nextType: string) => void;
  onToggleSchemaOptions?: (aiIndex: number, variable: string) => void;
  onSchemaOptionChange?: (
    aiIndex: number,
    variable: string,
    option: 'notNull' | 'unique' | 'primaryKey' | 'defaultValue',
    value: boolean | string
  ) => void;
  onConfirmSchema?: (aiIndex: number) => void;
  onAssistantTypingChange?: (isTyping: boolean) => void;
  typingStopSignal?: number;
};

export default function MessageList({
  messages,
  onRefreshResponse,
  onExecuteSql,
  onCancelSql,
  onExportFile,
  onSchemaTypeChange,
  onToggleSchemaOptions,
  onSchemaOptionChange,
  onConfirmSchema,
  onAssistantTypingChange,
  typingStopSignal = 0,
}: MessageListProps) {
  const [exportingIndex, setExportingIndex] = useState<number | null>(null);

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
    <div className="space-y-6">
      {messages.map((msg, index) => (
        <div key={index} className="w-full">
          {!msg.isUser &&
          msg.exportToExcel?.filename &&
          (msg.exportToExcel.base64 || msg.exportToExcel.sessionFileId) ? (
            <div className="flex justify-start w-full mb-2">
              <div className="w-full max-w-xs flex flex-col items-stretch gap-1 min-w-0">
                <div
                  className="flex flex-col gap-2 bg-gray-100 dark:bg-slate-800 text-gray-800 dark:text-gray-100 px-3 py-2.5 rounded-xl border border-gray-200 dark:border-slate-700 max-w-full min-w-0"
                  title={msg.exportToExcel.filename}
                >
                  <div className="flex items-start gap-2 min-w-0">
                    <svg
                      className="w-4 h-4 flex-shrink-0 mt-0.5 text-gray-600 dark:text-gray-300"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden
                    >
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                    </svg>
                    <span className="text-sm sm:text-base font-semibold leading-snug truncate min-w-0">
                      {msg.exportToExcel.filename}
                    </span>
                  </div>
                  <div className="flex justify-end w-full border-t border-gray-300 dark:border-slate-600 pt-2 mt-1">
                    <button
                      type="button"
                      disabled={!onExportFile || exportingIndex === index}
                      onClick={() => void runFileDownload(index)}
                      className="text-sm font-medium text-gray-800 hover:text-gray-950 disabled:opacity-50 dark:text-gray-200 dark:hover:text-white"
                    >
                      {exportingIndex === index ? '…' : 'Download'}
                    </button>
                  </div>
                </div>
                {typeof msg.exportToExcel.rowCount === 'number' && msg.exportToExcel.rowCount > 0 ? (
                  <span className="text-[11px] text-gray-500 dark:text-gray-400 pl-1">
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
            onTypingStateChange={
              !msg.isUser && index === messages.length - 1 ? onAssistantTypingChange : undefined
            }
            typingStopSignal={!msg.isUser && index === messages.length - 1 ? typingStopSignal : 0}
          />
          {!msg.isUser && msg.schemaPreview && (
            <div className="mt-3 mb-2 rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-3 py-2 bg-gray-50 text-xs font-medium text-gray-700">
                Schema review: `{msg.schemaPreview.tableName}`
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full text-xs">
                  <thead className="bg-white">
                    <tr>
                      <th className="text-left px-3 py-2 border-b border-gray-200">Variable</th>
                      <th className="text-left px-3 py-2 border-b border-gray-200">Type</th>
                    </tr>
                  </thead>
                  {msg.schemaPreview.columns.map((col) => (
                    <tbody key={col.variable}>
                        <tr className="odd:bg-white even:bg-gray-50/40">
                          <td className="px-3 py-2 border-b border-gray-100 font-mono text-gray-800">{col.variable}</td>
                          <td className="px-3 py-2 border-b border-gray-100">
                            <div className="flex items-center gap-2">
                              <div className="w-full space-y-1">
                                <select
                                  className="w-full rounded-md border border-gray-300 px-2 py-1 bg-white disabled:bg-gray-100 disabled:text-gray-500"
                                  value={SQL_TYPE_OPTIONS.includes(col.type) ? col.type : '__custom__'}
                                  disabled={!!msg.schemaLocked}
                                  onChange={(e) => {
                                    const v = e.target.value;
                                    if (v !== '__custom__') {
                                      onSchemaTypeChange?.(index, col.variable, v);
                                    } else {
                                      onSchemaTypeChange?.(index, col.variable, 'CUSTOM_TYPE');
                                    }
                                  }}
                                >
                                  {SQL_TYPE_OPTIONS.map((t) => (
                                    <option key={t} value={t}>{t}</option>
                                  ))}
                                  <option value="__custom__">Custom type...</option>
                                </select>
                                {!SQL_TYPE_OPTIONS.includes(col.type) && (
                                  <input
                                    type="text"
                                    className="w-full rounded-md border border-gray-300 px-2 py-1 bg-white disabled:bg-gray-100 disabled:text-gray-500"
                                    value={col.type}
                                    disabled={!!msg.schemaLocked}
                                    onChange={(e) => onSchemaTypeChange?.(index, col.variable, e.target.value)}
                                    placeholder="Nhập type tùy chỉnh"
                                  />
                                )}
                              </div>
                              <button
                                type="button"
                                disabled={!!msg.schemaLocked}
                                onClick={() => onToggleSchemaOptions?.(index, col.variable)}
                                className="w-7 h-7 rounded-md border border-gray-300 text-gray-700 hover:bg-gray-100 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
                                title="More options"
                              >
                                +
                              </button>
                            </div>
                          </td>
                        </tr>
                        {col.showOptions && (
                          <tr>
                            <td colSpan={2} className="px-3 py-2 border-b border-gray-100 bg-gray-50/50">
                              <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs">
                                <label className="flex items-center gap-2">
                                  <input
                                    type="checkbox"
                                    checked={!!col.notNull}
                                    disabled={!!msg.schemaLocked}
                                    onChange={(e) => onSchemaOptionChange?.(index, col.variable, 'notNull', e.target.checked)}
                                  />
                                  NOT NULL
                                </label>
                                <label className="flex items-center gap-2">
                                  <input
                                    type="checkbox"
                                    checked={!!col.unique}
                                    disabled={!!msg.schemaLocked}
                                    onChange={(e) => onSchemaOptionChange?.(index, col.variable, 'unique', e.target.checked)}
                                  />
                                  UNIQUE
                                </label>
                                <label className="flex items-center gap-2">
                                  <input
                                    type="checkbox"
                                    checked={!!col.primaryKey}
                                    disabled={!!msg.schemaLocked}
                                    onChange={(e) => onSchemaOptionChange?.(index, col.variable, 'primaryKey', e.target.checked)}
                                  />
                                  PRIMARY KEY
                                </label>
                                <label className="flex items-center gap-2">
                                  <span>DEFAULT</span>
                                  <input
                                    type="text"
                                    value={col.defaultValue || ''}
                                    disabled={!!msg.schemaLocked}
                                    onChange={(e) => onSchemaOptionChange?.(index, col.variable, 'defaultValue', e.target.value)}
                                    className="w-full rounded-md border border-gray-300 px-2 py-1 bg-white disabled:bg-gray-100"
                                    placeholder="value"
                                  />
                                </label>
                              </div>
                            </td>
                          </tr>
                        )}
                    </tbody>
                  ))}
                </table>
              </div>
              <div className="px-3 py-2 bg-white flex justify-end">
                <button
                  type="button"
                  onClick={() => onConfirmSchema?.(index)}
                  disabled={!!msg.schemaLocked}
                  className="text-xs px-3 py-1.5 rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
                >
                  {msg.schemaLocked ? 'Schema confirmed' : 'Confirm schema'}
                </button>
              </div>
            </div>
          )}

          {!msg.isUser && (
            <div className="mt-2 mb-2 flex items-center gap-3 text-xs">
              {onRefreshResponse && (
                <button
                  type="button"
                  onClick={() => void onRefreshResponse(index)}
                  className="flex items-center gap-1 text-gray-500 hover:text-gray-700 transition-colors"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                    />
                  </svg>
                  <span>Refresh response</span>
                </button>
              )}
              {msg.sqlToExecute && onExecuteSql && (
                <>
                  {onCancelSql && (
                    <button
                      type="button"
                      onClick={() => void onCancelSql(index)}
                      disabled={msg.sqlActionState === 'executed' || msg.sqlActionState === 'cancelled' || msg.sqlActionState === 'running'}
                      className="flex items-center gap-1 text-gray-400 hover:text-gray-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M6 18L18 6M6 6l12 12"
                        />
                      </svg>
                      <span>Cancel</span>
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => void onExecuteSql(index)}
                    disabled={msg.sqlActionState === 'executed' || msg.sqlActionState === 'cancelled' || msg.sqlActionState === 'running'}
                    className="flex items-center gap-1 text-emerald-600 hover:text-emerald-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                    <span>Execute SQL</span>
                  </button>
                </>
              )}
            </div>
          )}

        </div>
      ))}
    </div>
  );
}

