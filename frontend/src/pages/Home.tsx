import { useEffect, useRef, useState } from 'react';
import MessageList, { type UiMessage } from '../components/chat/MessageList';
import { sendMessage, uploadExcel } from '../services/api';
import plusIcon from '../assets/icons/Plus.svg';
import microphoneIcon from '../assets/icons/Microphone.svg';
import arrowUpCircleIcon from '../assets/icons/Arrow-up-circle.svg';

const MAX_TEXTAREA_HEIGHT = 200;
const MIN_TEXTAREA_HEIGHT = 60;

export default function Home() {
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isUploadingExcel, setIsUploadingExcel] = useState(false);
  const [attachedExcel, setAttachedExcel] = useState<{ originalName: string; serverPath: string } | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const canSend = !isLoading && !isUploadingExcel && (query.trim().length > 0 || attachedExcel != null);

  const handleExcelFileSelected = async (file: File) => {
    setIsUploadingExcel(true);
    try {
      const res = await uploadExcel(file, sessionId, null);
      if (!res.success) {
        window.alert(res.error || 'Failed to upload Excel file');
        return;
      }
      setAttachedExcel({ originalName: res.file.original_name, serverPath: res.file.server_path });
      if (query.trim().length === 0) {
        setQuery(`Tóm tắt file Excel "${res.file.original_name}"`);
        setTimeout(() => textareaRef.current?.focus(), 0);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to upload Excel file';
      window.alert(message);
    } finally {
      setIsUploadingExcel(false);
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    void handleExcelFileSelected(file);
  };

  const sendText = async () => {
    if (isLoading || isUploadingExcel) return;
    const hasText = query.trim().length > 0;
    if (!hasText && !attachedExcel) return;

    const displayText = hasText ? query.trim() : `Uploaded Excel: ${attachedExcel?.originalName ?? ''}`.trim();
    let sendPayload = displayText;
    if (attachedExcel) {
      const prompt =
        hasText && displayText
          ? displayText
          : `Hãy đọc và tóm tắt file Excel "${attachedExcel.originalName}".`;
      sendPayload =
        `${prompt}\n\n` +
        `[UPLOADED_EXCEL_PATH_START]\n${attachedExcel.serverPath}\n[UPLOADED_EXCEL_PATH_END]\n` +
        `[UPLOADED_EXCEL_NAME_START]\n${attachedExcel.originalName}\n[UPLOADED_EXCEL_NAME_END]\n`;
    }

    setMessages((prev) => [...prev, { text: displayText, isUser: true }]);
    setQuery('');
    setIsLoading(true);
    try {
      const res = await sendMessage(sendPayload, sessionId, null);
      if (res.success) {
        setMessages((prev) => [...prev, { text: res.response, isUser: false }]);
        if (res.session_id) setSessionId(res.session_id);
      } else {
        setMessages((prev) => [
          ...prev,
          { text: `Error: ${res.error || 'Failed to get response'}`, isUser: false },
        ]);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to connect';
      setMessages((prev) => [...prev, { text: `Error: ${msg}`, isUser: false }]);
    } finally {
      setIsLoading(false);
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
    if (attachedExcel) setAttachedExcel(null);
  };

  const handleSend = () => {
    void sendText();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

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

  const hasMessages = messages.length > 0;

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Danh sách tin nhắn */}
      {hasMessages && (
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6">
          <div className="max-w-3xl mx-auto">
            <MessageList messages={messages} />
            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      {/* Khu vực nhập + greeting (giống ảnh: Hi How are you today?, ô nhập trắng viền xám, + / loa / mic) */}
      <div
        className={`flex flex-col pb-6 pt-4 ${hasMessages ? '' : 'flex-1 justify-center'}`}
      >
        <div className="max-w-5xl mx-auto w-full px-4">
          {!hasMessages && (
            <h1 className="text-4xl md:text-5xl font-bold text-slate-800 mb-8 text-center">
              Hi, How are you today?
            </h1>
          )}
          {/* Khung input giống Chat: border-2 gray-300, rounded-3xl, shadow-lg, + / Ask anything / loa + mic */}
          <div className="relative bg-white border-2 border-gray-300 rounded-3xl px-4 shadow-lg">
            <div className="flex items-center gap-3 min-h-[48px]">
              <button
                type="button"
                className="text-gray-500 hover:text-gray-700 flex-shrink-0"
                onClick={() => fileInputRef.current?.click()}
                aria-label="Upload Excel"
              >
                <img src={plusIcon} alt="Add" className="w-5 h-5" />
              </button>
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                multiple={false}
                accept=".xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,text/csv"
                onChange={handleFileInputChange}
              />
              <textarea
                ref={textareaRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask anything"
                rows={1}
                className="flex-1 resize-none outline-none text-lg min-w-0"
                style={{
                  maxHeight: `${MAX_TEXTAREA_HEIGHT}px`,
                  minHeight: `${MIN_TEXTAREA_HEIGHT}px`,
                  paddingTop: '20px',
                  paddingBottom: '20px',
                }}
                disabled={isLoading}
              />
              <div className="flex items-center gap-2 flex-shrink-0">
                <button type="button" onClick={() => {}} aria-label="Microphone">
                  <img src={microphoneIcon} alt="Microphone" className="w-5 h-5" />
                </button>
                <button
                  type="button"
                  onClick={() => void handleSend()}
                  disabled={!canSend}
                  className="flex items-center justify-center w-10 h-10 rounded-full p-0 opacity-60 hover:opacity-100 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
                  aria-label="Send"
                >
                  <img src={arrowUpCircleIcon} alt="" className="w-20 h-20" />
                </button>
              </div>
            </div>
          </div>
          {/* Các icon bên dưới: chỉ hiện khi chưa có chat, chỉ trang trí */}
          {!hasMessages && (
          <div className="w-full max-w-5xl flex flex-wrap justify-center gap-3 mt-6">
            <div className="flex items-center gap-2 px-6 py-3 bg-white border-2 border-gray-300 rounded-xl hover:border-gray-400 hover:bg-gray-50 transition-colors font-medium text-gray-700 disabled:opacity-50 cursor-default select-none">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
              <span>Analyze</span>
            </div>
            <div className="flex items-center gap-2 px-6 py-3 bg-white border-2 border-gray-300 rounded-xl hover:border-gray-400 hover:bg-gray-50 transition-colors font-medium text-gray-700 disabled:opacity-50 cursor-default select-none">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
              </svg>
              <span>SQL</span>
            </div>
            <div className="flex items-center gap-2 px-6 py-3 bg-white border-2 border-gray-300 rounded-xl hover:border-gray-400 hover:bg-gray-50 transition-colors font-medium text-gray-700 disabled:opacity-50 cursor-default select-none  ">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <span>Summarize Text</span>
            </div>
            <div className="flex items-center gap-2 px-6 py-3 bg-white border-2 border-gray-300 rounded-xl hover:border-gray-400 hover:bg-gray-50 transition-colors font-medium text-gray-700 disabled:opacity-50 cursor-default select-none  ">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l9-5-9-5-9 5 9 5z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z" />
              </svg>
              <span>Business Insight</span>
            </div>
          </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="w-full flex items-center justify-between px-6 py-4 border-t border-gray-200">
        <p className="text-sm text-gray-600 italic text-center flex-1">
          By using LightDBee, you agree to our Term and Service Policy
        </p>
        <button
          type="button"
          className="w-8 h-8 rounded-full bg-gray-100 hover:bg-gray-200 flex items-center justify-center transition-colors ml-4"
          aria-label="Help"
        >
          <svg className="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </button>
      </div>
    </div>
  );
}

