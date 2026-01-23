import React, { useEffect, useMemo, useRef, useState } from 'react';
import MessageList, { type UiMessage } from '../components/chat/MessageList';
import { getSession, sendMessage } from '../services/api';
import plusIcon from '../assets/icons/Plus.svg';
import speakerIcon from '../assets/icons/Speaker.svg';
import microphoneIcon from '../assets/icons/Microphone.svg';
import helpIcon from '../assets/icons/Help.svg';

const MAX_TEXTAREA_HEIGHT = 200;
const MIN_TEXTAREA_HEIGHT = 60;

type ChatProps = {
  sessionId?: string | null;
  onSessionIdChange?: (sessionId: string | null) => void;
};

export default function Chat({ sessionId: propSessionId, onSessionIdChange }: ChatProps) {
  const [query, setQuery] = useState<string>('');
  const [messages, setMessages] = useState<UiMessage[]>([]);
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
          const convertedMessages: UiMessage[] = res.messages
            .filter((msg: any) => msg.role === 'user' || msg.role === 'assistant')
            .map((msg: any) => ({
              text: msg.content || '',
              isUser: msg.role === 'user',
            }));
          setMessages(convertedMessages);
          setSessionId(sid);
          onSessionIdChange?.(sid);
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
      setMessages([]);
      setSessionId(null);
      onSessionIdChange?.(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
          onSessionIdChange?.(res.session_id);
        }
      } else {
        setMessages((prev) => [...prev, { text: `Error: ${res.error || 'Failed to get response'}`, isUser: false }]);
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
    <div className="flex flex-col h-full bg-white relative">
      {/* Chat Content */}
      <div className="flex-1 overflow-y-auto px-8 py-6">
        <div className="max-w-4xl mx-auto">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full">
              <h1 className="text-4xl md:text-5xl font-bold text-gray-900 mb-8 text-center">
                How are you today?
              </h1>
            </div>
          ) : (
            <>
              <MessageList messages={messages} onRefreshResponse={(idx) => void handleRefreshResponse(idx)} />
              <div ref={messagesEndRef} />
            </>
          )}
        </div>
      </div>

      {/* Input Field */}
      <div className="px-8 pb-8">
        <div className="max-w-4xl mx-auto">
          <div className="relative bg-white border-2 border-gray-300 rounded-2xl px-4 py-4 shadow-sm hover:border-gray-400 transition-colors">
            <div className="flex items-center gap-3">
              {/* Plus Icon */}
              <button
                type="button"
                className="text-gray-500 hover:text-gray-700 transition-colors"
              >
                <img src={plusIcon} alt="Add" className="w-5 h-5" />
              </button>

              {/* Input */}
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
                placeholder="Ask anything"
                rows={1}
                className="flex-1 outline-none text-gray-900 placeholder-gray-500 resize-none min-h-[40px] py-2 break-words whitespace-pre-wrap text-lg"
                style={{
                  maxHeight: `${MAX_TEXTAREA_HEIGHT}px`,
                  wordWrap: 'break-word',
                  overflowWrap: 'break-word',
                  lineHeight: '1.5',
                }}
              />

              {/* Speaker and Microphone Icons */}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="text-gray-500 hover:text-gray-700 transition-colors"
                >
                  <img src={speakerIcon} alt="Speaker" className="w-5 h-5" />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    // Voice input functionality
                    console.log('Voice input clicked');
                  }}
                  className="text-gray-500 hover:text-gray-700 transition-colors"
                >
                  <img src={microphoneIcon} alt="Microphone" className="w-5 h-5" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Help Icon - Bottom Right */}
      <button className="fixed bottom-6 right-6 w-10 h-10 rounded-full bg-gray-100 hover:bg-gray-200 flex items-center justify-center transition-colors z-10">
        <img src={helpIcon} alt="Help" className="w-5 h-5" />
      </button>
    </div>
  );
}

