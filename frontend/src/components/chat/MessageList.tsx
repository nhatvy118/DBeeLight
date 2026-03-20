import ChatMessage from './ChatMessage';

export type ExportData = {
  base64?: string;
  filename?: string;
  rowCount?: number;
  tableName?: string; // For backward compatibility
};

export type UiMessage = {
  text: string;
  isUser: boolean;
  sqlToExecute?: string | null;
  exportToExcel?: ExportData | null;
};

type MessageListProps = {
  messages: UiMessage[];
  onRefreshResponse?: (aiIndex: number) => void;
  onExecuteSql?: (aiIndex: number) => void;
  onCancelSql?: (aiIndex: number) => void;
  onExportExcel?: (aiIndex: number) => void;
  onAssistantTypingChange?: (isTyping: boolean) => void;
  typingStopSignal?: number;
};

export default function MessageList({
  messages,
  onRefreshResponse,
  onExecuteSql,
  onCancelSql,
  onExportExcel,
  onAssistantTypingChange,
  typingStopSignal = 0,
}: MessageListProps) {
  if (messages.length === 0) return null;

  return (
    <div className="space-y-1">
      {messages.map((msg, index) => (
        <div key={index} className={msg.isUser ? '' : 'w-full border-b border-gray-100 last:border-b-0'}>
          <ChatMessage
            message={msg.text}
            isUser={msg.isUser}
            onTypingStateChange={
              !msg.isUser && index === messages.length - 1 ? onAssistantTypingChange : undefined
            }
            typingStopSignal={!msg.isUser && index === messages.length - 1 ? typingStopSignal : 0}
          />
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
              {msg.exportToExcel && onExportExcel && (
                <button
                  type="button"
                  onClick={() => void onExportExcel(index)}
                  className="flex items-center gap-1 text-blue-600 hover:text-blue-700 transition-colors"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                    />
                  </svg>
                  <span>Export Excel</span>
                </button>
              )}
              {msg.sqlToExecute && onExecuteSql && (
                <>
                  {onCancelSql && (
                    <button
                      type="button"
                      onClick={() => void onCancelSql(index)}
                      className="flex items-center gap-1 text-gray-400 hover:text-gray-600 transition-colors"
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
                    className="flex items-center gap-1 text-emerald-600 hover:text-emerald-700 transition-colors"
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

