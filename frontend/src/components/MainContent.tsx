import React, { useEffect, useMemo, useRef, useState } from 'react';
import ChatMessage from './ChatMessage';
import { sendMessage, getSession } from '../services/api';

type Message = {
  text: string;
  isUser: boolean;
};

const MAX_TEXTAREA_HEIGHT = 200;
const MIN_TEXTAREA_HEIGHT = 60;

type MainContentProps = {
  sessionId?: string | null;
  onSessionIdChange?: (sessionId: string | null) => void;
};

export default function MainContent({ sessionId: propSessionId, onSessionIdChange }: MainContentProps) {
  const [query, setQuery] = useState<string>('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [sessionId, setSessionId] = useState<string | null>(propSessionId || null);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const canSend = useMemo(() => !isLoading && query.trim().length > 0, [isLoading, query]);

  // Load session when sessionId prop changes
  useEffect(() => {
    const loadSession = async (sid: string) => {
      try {
        setIsLoading(true);
        const res = await getSession(sid);
        if (res.success && res.messages) {
          // Convert session messages to Message format
          const convertedMessages: Message[] = res.messages
            .filter((msg: any) => msg.role === 'user' || msg.role === 'assistant')
            .map((msg: any) => ({
              text: msg.content || '',
              isUser: msg.role === 'user',
            }));
          setMessages(convertedMessages);
          setSessionId(sid);
          if (onSessionIdChange) {
            onSessionIdChange(sid);
          }
        }
      } catch (err) {
        console.error('Failed to load session:', err);
        window.alert('Failed to load chat history');
      } finally {
        setIsLoading(false);
      }
    };

    if (propSessionId && propSessionId !== sessionId) {
      void loadSession(propSessionId);
    } else if (!propSessionId && sessionId) {
      // Clear messages if sessionId is cleared
      setMessages([]);
      setSessionId(null);
      if (onSessionIdChange) {
        onSessionIdChange(null);
      }
    }
  }, [propSessionId]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Auto-resize textarea (grow until MAX_TEXTAREA_HEIGHT, then scroll)
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const scrollHeight = el.scrollHeight;
    const newHeight = Math.max(MIN_TEXTAREA_HEIGHT, Math.min(scrollHeight, MAX_TEXTAREA_HEIGHT));
    el.style.height = `${newHeight}px`;
    el.style.overflowY = scrollHeight > MAX_TEXTAREA_HEIGHT ? 'auto' : 'hidden';
  }, [query]);

  const doSend = async (text: string) => {
    setIsLoading(true);
    try {
      const res = await sendMessage(text, sessionId);
      if (res.success) {
        setMessages((prev) => [...prev, { text: res.response, isUser: false }]);
        if (res.session_id) {
          setSessionId(res.session_id);
          if (onSessionIdChange) {
            onSessionIdChange(res.session_id);
          }
        }
      } else {
        setMessages((prev) => [
          ...prev,
          { text: `Error: ${res.error || 'Failed to get response'}`, isUser: false },
        ]);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to connect to server';
      setMessages((prev) => [...prev, { text: `Error: ${message}`, isUser: false }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = async () => {
    const text = query.trim();
    if (!text || isLoading) return;

    setMessages((prev) => [...prev, { text, isUser: true }]);
    setQuery('');
    await doSend(text);
  };

  const handleRefreshResponse = async (aiIndex: number) => {
    const userIndex = aiIndex - 1;
    if (userIndex < 0) return;
    const userMsg = messages[userIndex];
    if (!userMsg?.isUser) return;

    setIsLoading(true);
    try {
      const res = await sendMessage(userMsg.text, sessionId);
      if (res.success) {
        setMessages((prev) => {
          const updated = [...prev];
          updated[aiIndex] = { text: res.response, isUser: false };
          return updated;
        });
      } else {
        window.alert(`Error: ${res.error || 'Failed to refresh response'}`);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to refresh response';
      window.alert(`Error: ${message}`);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-screen relative overflow-hidden">
      {/* Background Gradient */}
      <div className="absolute inset-0 bg-gradient-to-b from-white via-white to-blue-50">
        <div className="absolute inset-0 opacity-30">
          <div className="absolute top-1/4 right-1/4 w-96 h-96 bg-pink-200 rounded-full blur-3xl" />
          <div className="absolute bottom-1/4 left-1/4 w-96 h-96 bg-purple-200 rounded-full blur-3xl" />
        </div>
      </div>

      {/* Chat Content */}
      <div className="relative z-10 flex-1 overflow-y-auto px-8 py-6">
        <div className="max-w-4xl mx-auto">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full">
              {/* Robot Avatar */}
              <div className="mb-8 relative w-80 h-80">
                <div className="absolute inset-0 w-64 h-64 rounded-full border-4 border-pink-400 mx-auto" />
                <div className="absolute inset-4 w-56 h-56 rounded-full bg-lime-400 mx-auto" />

                <div className="relative w-48 h-48 mx-auto mt-8">
                  <div className="absolute top-0 left-1/2 transform -translate-x-1/2 w-32 h-32 bg-blue-700 rounded-full shadow-lg">
                    <div className="absolute top-8 left-1/2 transform -translate-x-1/2 w-12 h-12 bg-white rounded-full">
                      <div className="absolute top-2 left-1/2 transform -translate-x-1/2 w-8 h-8 bg-black rounded-full" />
                    </div>
                  </div>

                  <div className="absolute top-24 left-1/2 transform -translate-x-1/2 w-24 h-32 bg-blue-600 rounded-lg shadow-md" />
                  <div className="absolute top-28 left-4 w-6 h-16 bg-blue-700 rounded-full" />
                  <div className="absolute top-28 right-4 w-6 h-16 bg-blue-700 rounded-full" />
                </div>

                <div className="absolute top-8 right-8 w-40 h-1 bg-blue-300 rounded-full transform rotate-12 opacity-70" />
                <div className="absolute top-20 right-12 w-32 h-1 bg-blue-300 rounded-full transform -rotate-12 opacity-70" />
                <div className="absolute top-1/2 right-0 w-32 h-32 border-2 border-blue-200 rounded-full opacity-50 transform translate-x-8" />
              </div>

              <h1 className="text-2xl font-semibold text-gray-900">Hello! How may I help you?</h1>
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((msg, index) => (
                <div key={index} className={!msg.isUser ? 'flex flex-col items-start' : ''}>
                  <ChatMessage message={msg.text} isUser={msg.isUser} />
                  {!msg.isUser && (
                    <button
                      type="button"
                      onClick={() => void handleRefreshResponse(index)}
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
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>
      </div>

      {/* Input Field */}
      <div className="relative z-10 px-8 pb-8">
        <div className="max-w-4xl mx-auto">
          <div className="relative bg-gradient-to-r from-blue-200 via-blue-300 to-purple-300 rounded-2xl p-1 shadow-lg">
            <div className="bg-white rounded-xl p-4 flex flex-col gap-3">
              {/* Top Section: Input Area */}
              <div className="flex items-start gap-3">
                {/* File and Microphone Icons */}
                <div className="flex items-center gap-2 pt-2">
                  <button type="button" className="flex items-center gap-1 text-gray-500 hover:text-gray-700 transition-colors">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
                      />
                    </svg>
                    <span className="text-sm font-medium">0</span>
                  </button>

                  <button
                    type="button"
                    className="w-10 h-10 rounded-full bg-gray-100 hover:bg-gray-200 flex items-center justify-center text-gray-500 transition-colors"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
                      />
                    </svg>
                  </button>
                </div>

                <textarea
                  ref={textareaRef}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      void handleSend();
                    }
                  }}
                  placeholder="Type you Query here!"
                  rows={1}
                  className="flex-1 outline-none text-gray-700 placeholder-gray-400 resize-none min-h-[60px] py-2 break-words whitespace-pre-wrap"
                  style={{
                    maxHeight: `${MAX_TEXTAREA_HEIGHT}px`,
                    wordWrap: 'break-word',
                    overflowWrap: 'break-word',
                    lineHeight: '1.5',
                  }}
                />

                <button
                  type="button"
                  onClick={() => void handleSend()}
                  disabled={!canSend}
                  className="mt-2 w-12 h-12 bg-blue-500 hover:bg-blue-600 disabled:bg-gray-400 disabled:cursor-not-allowed rounded-full flex items-center justify-center text-white transition-colors shadow-md flex-shrink-0"
                >
                  {isLoading ? (
                    <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                      />
                    </svg>
                  ) : (
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7-7m0 0l7 7m-7-7v18" />
                    </svg>
                  )}
                </button>
              </div>

              {/* Bottom Section: Action Buttons */}
              <div className="flex items-center gap-2 pt-2 border-t border-gray-200">
                <button
                  type="button"
                  className="px-4 py-2 bg-white hover:bg-gray-50 border border-blue-300 rounded-lg text-sm font-medium text-gray-700 flex items-center gap-2 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9"
                    />
                  </svg>
                  Web Search
                </button>

                <button
                  type="button"
                  className="px-4 py-2 bg-white hover:bg-gray-50 border border-blue-300 rounded-lg text-sm font-medium text-gray-700 flex items-center gap-2 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                  Deep Think
                </button>

                <button
                  type="button"
                  className="px-4 py-2 bg-white hover:bg-gray-50 border border-blue-300 rounded-lg text-sm font-medium text-gray-700 flex items-center gap-2 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
                    />
                  </svg>
                  Database Connected
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}


