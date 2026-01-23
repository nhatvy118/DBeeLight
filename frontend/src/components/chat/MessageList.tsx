import ChatMessage from './ChatMessage';

export type UiMessage = {
  text: string;
  isUser: boolean;
};

type MessageListProps = {
  messages: UiMessage[];
  onRefreshResponse?: (aiIndex: number) => void;
};

export default function MessageList({ messages, onRefreshResponse }: MessageListProps) {
  if (messages.length === 0) return null;

  return (
    <div className="space-y-4">
      {messages.map((msg, index) => (
        <div key={index} className={!msg.isUser ? 'flex flex-col items-start' : ''}>
          <ChatMessage message={msg.text} isUser={msg.isUser} />
          {!msg.isUser && onRefreshResponse && (
            <button
              type="button"
              onClick={() => void onRefreshResponse(index)}
              className="mt-2 flex items-center gap-1 text-gray-500 hover:text-gray-700 text-xs transition-colors"
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
        </div>
      ))}
    </div>
  );
}

