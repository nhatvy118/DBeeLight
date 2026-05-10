import { useEffect, useRef, useState } from 'react';
import MessageList, { type UiMessage } from '../components/chat/MessageList';
import {
  sendMessage,
  createSession,
  uploadSessionFile,
  listUserFilesInventory,
  deleteSessionFile,
} from '../services/api';
import { buildChatMessageWithSessionFiles } from '../utils/sessionFileMarkers';
import plusIcon from '../assets/icons/Plus.svg';
import fileIcon from '../assets/icons/File.svg';
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
  const [inputAttachedFiles, setInputAttachedFiles] = useState<{ id: string; filename: string }[]>([]);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const canSend = !isLoading && !isUploadingExcel && query.trim().length > 0;

  const handleRemoveSessionFile = async (fileId: string) => {
    try {
      await deleteSessionFile(fileId);
      setMessages((prev) =>
        prev.flatMap((m) => {
          if (!m.isUser || !m.attachments?.some((a) => a.fileId === fileId)) return [m];
          const nextAtt = m.attachments.filter((a) => a.fileId !== fileId);
          if (nextAtt.length === 0 && !m.text.trim()) return [];
          return [{ ...m, attachments: nextAtt.length ? nextAtt : undefined }];
        }),
      );
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Remove failed');
    }
  };

  const handleRemoveInputAttachment = async (fileId: string) => {
    try {
      await deleteSessionFile(fileId);
      setInputAttachedFiles((prev) => prev.filter((f) => f.id !== fileId));
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Remove failed');
    }
  };

  const handleFileSelected = async (file: File) => {
    setIsUploadingExcel(true);
    try {
      let sid = sessionId;
      if (!sid) {
        const cr = await createSession(null, null);
        if (!cr.success || !cr.session_id) {
          window.alert('Could not start session');
          return;
        }
        sid = cr.session_id;
        setSessionId(sid);
      }
      const { file: uploaded } = await uploadSessionFile(sid!, file, null);
      setInputAttachedFiles((prev) => [...prev, { id: uploaded.id, filename: uploaded.filename }]);
      if (query.trim().length === 0) {
        setQuery(`Tóm tắt file "${file.name}"`);
      }
      setTimeout(() => textareaRef.current?.focus(), 0);
    } catch (err) {
      const e = err as Error & { code?: string };
      if (e.code === 'storage_quota_exceeded' || /5\s*GB|storage limit/i.test(e.message || '')) {
        try {
          const inv = await listUserFilesInventory();
          const lines = inv
            .slice(0, 12)
            .map(
              (r) =>
                `• ${r.filename} (${(r.size_bytes / (1024 * 1024)).toFixed(1)} MB) — phiên ${r.session_id.slice(0, 8)}…`,
            );
          window.alert(
            'Bạn đã dùng hết 5 GB dung lượng lưu trữ cho file đã tải. Hãy xóa bớt file (× trên chip ở ô nhập hoặc trong khung chat) rồi thử lại.\n\n' +
              (lines.length ? `Một số file gần đây:\n${lines.join('\n')}` : ''),
          );
        } catch {
          window.alert(
            'Bạn đã dùng hết 5 GB dung lượng lưu trữ. Hãy xóa file (× trên chip ở ô nhập hoặc trong khung chat) rồi thử lại.',
          );
        }
      } else {
        window.alert(e instanceof Error ? e.message : 'Upload failed');
      }
    } finally {
      setIsUploadingExcel(false);
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    void handleFileSelected(file);
  };

  const sendText = async () => {
    if (isLoading || isUploadingExcel) return;
    const hasText = query.trim().length > 0;
    if (!hasText) return;

    const displayText = query.trim();
    const sendPayload = buildChatMessageWithSessionFiles(displayText, inputAttachedFiles);
    const attachmentsForUi = inputAttachedFiles.map((f) => ({ name: f.filename, fileId: f.id }));

    setMessages((prev) => [
      ...prev,
      {
        text: displayText,
        isUser: true,
        ...(attachmentsForUi.length > 0 ? { attachments: attachmentsForUi } : {}),
      },
    ]);
    setInputAttachedFiles([]);
    setQuery('');
    setIsLoading(true);
    try {
      const res = await sendMessage(sendPayload, sessionId, null);
      if (res.success) {
        setMessages((prev) => [...prev, { text: res.response ?? '', isUser: false }]);
        if (res.session_id) {
          setSessionId(res.session_id);
        }
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
      {hasMessages && (
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6">
          <div className="max-w-3xl mx-auto">
            <MessageList
              messages={messages}
              onRemoveSessionFile={(fid) => void handleRemoveSessionFile(fid)}
            />
            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      <div className={`flex flex-col pb-6 pt-4 ${hasMessages ? '' : 'flex-1 justify-center'}`}>
        <div className="max-w-5xl mx-auto w-full px-4">
          {!hasMessages && (
            <h1 className="text-4xl md:text-5xl font-bold text-slate-800 mb-8 text-center">
              Hi, How are you today?
            </h1>
          )}
          <div className="relative bg-white border-2 border-gray-300 rounded-3xl px-4 shadow-lg">
            {(inputAttachedFiles.length > 0 || isUploadingExcel) && (
              <div className="flex flex-wrap gap-2 pt-3 pb-1">
                {isUploadingExcel && <span className="text-xs text-gray-500">Đang tải file…</span>}
                {inputAttachedFiles.map((f) => (
                  <span
                    key={f.id}
                    className="inline-flex items-center gap-2 text-xs bg-gray-100 text-gray-700 px-3 py-1 rounded-full"
                  >
                    <img src={fileIcon} alt="" className="w-4 h-4" />
                    <span className="max-w-[200px] truncate">{f.filename}</span>
                    <button
                      type="button"
                      className="text-gray-500 hover:text-gray-800"
                      onClick={() => void handleRemoveInputAttachment(f.id)}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="flex items-center gap-3 min-h-[48px]">
              <button
                type="button"
                className="text-gray-500 hover:text-gray-700 flex-shrink-0"
                onClick={() => fileInputRef.current?.click()}
                aria-label="Attach file"
              >
                <img src={plusIcon} alt="Add" className="w-5 h-5" />
              </button>
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                multiple={false}
                accept=".xlsx,.xls,.csv,.pdf,.db,.sqlite,.txt,.md,application/pdf,text/csv"
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
          {!hasMessages && (
            <div className="w-full max-w-5xl flex flex-wrap justify-center gap-3 mt-6">
              <div className="flex items-center gap-2 px-6 py-3 bg-white border-2 border-gray-300 rounded-xl font-medium text-gray-700 cursor-default select-none">
                <span>Analyze</span>
              </div>
              <div className="flex items-center gap-2 px-6 py-3 bg-white border-2 border-gray-300 rounded-xl font-medium text-gray-700 cursor-default select-none">
                <span>SQL</span>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="w-full flex items-center justify-between px-6 py-4 border-t border-gray-200">
        <p className="text-sm text-gray-600 italic text-center flex-1">
          By using LightDBee, you agree to our Term and Service Policy
        </p>
      </div>
    </div>
  );
}
