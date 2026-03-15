import React, { useEffect, useMemo, useRef, useState } from 'react';
import MessageList, { type UiMessage, type ExportData } from '../components/chat/MessageList';
import { getSession, sendMessage, getSessions, executeSql, exportData, uploadExcel, type SessionInfo } from '../services/api';
import plusIcon from '../assets/icons/Plus.svg';
import microphoneIcon from '../assets/icons/Microphone.svg';
import arrowUpCircleIcon from '../assets/icons/Arrow-up-circle.svg';
import helpIcon from '../assets/icons/Help.svg';
import fileIcon from '../assets/icons/File.svg';

const MAX_TEXTAREA_HEIGHT = 200;
const MIN_TEXTAREA_HEIGHT = 60;

const STORAGE_LAST_SESSION_ID = 'lastSessionId';
const STORAGE_LAST_SESSION_PROJECT = 'lastSessionIdForProject';

// Detect language from text (simple heuristic)
function detectLanguage(text: string): string {
  const vietnameseChars = /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]/i;
  if (vietnameseChars.test(text)) {
    return 'vi';
  }
  return 'en';
}

function saveLastSession(sessionId: string | null, projectId: string | null) {
  if (sessionId) {
    localStorage.setItem(STORAGE_LAST_SESSION_ID, sessionId);
    localStorage.setItem(STORAGE_LAST_SESSION_PROJECT, projectId ?? '');
  } else {
    localStorage.removeItem(STORAGE_LAST_SESSION_ID);
    localStorage.removeItem(STORAGE_LAST_SESSION_PROJECT);
  }
}

function getLastSession(projectId: string | null): string | null {
  const stored = localStorage.getItem(STORAGE_LAST_SESSION_ID);
  const storedProject = localStorage.getItem(STORAGE_LAST_SESSION_PROJECT) || '';
  if (!stored) return null;
  const currentProject = projectId ?? '';
  if (storedProject !== currentProject) return null;
  return stored;
}

type ChatProps = {
  projectId?: string | null;
  sessionId?: string | null;
  onSessionIdChange?: (sessionId: string | null) => void;
};

export default function Chat({ projectId: propProjectId, sessionId: propSessionId, onSessionIdChange }: ChatProps) {
  const [query, setQuery] = useState<string>('');
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  // Don't init from propSessionId: so on reload with URL like /chat/projectId/sessionId,
  // the "load session" effect sees propSessionId set but sessionId null and fetches messages.
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState<{ id: string; name: string } | null>(null);
  const [projectSessions, setProjectSessions] = useState<SessionInfo[]>([]);
  const [sessionPreviews, setSessionPreviews] = useState<Record<string, string>>({});
  const [inputKey, setInputKey] = useState(0);
  const previousProjectIdRef = useRef<string | null>(null);
  const hasRestoredSessionRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [isUploadingExcel, setIsUploadingExcel] = useState(false);
  const [attachedExcel, setAttachedExcel] = useState<{
    originalName: string;
    serverPath: string;
    sizeBytes: number;
  } | null>(null);

  // Load selected project from URL (propProjectId) - URL is source of truth
  useEffect(() => {
    if (propProjectId) {
      // Load project from URL
      const projects = JSON.parse(localStorage.getItem('projects') || '[]');
      const project = projects.find((p: { id: string }) => p.id === propProjectId);
      if (project) {
        setSelectedProject({ id: project.id, name: project.name });
        previousProjectIdRef.current = project.id;
      } else {
        // Project not found, clear selection
        setSelectedProject(null);
        previousProjectIdRef.current = null;
      }
    } else {
      // No project in URL, clear selection
      setSelectedProject(null);
      previousProjectIdRef.current = null;
    }
  }, [propProjectId]);

  // No longer listen to localStorage - URL is source of truth

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const extractLastMutationSqlBlock = (text: string): string | null => {
    const regex = /```sql([\s\S]*?)```/gi;
    let match: RegExpExecArray | null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let last: string | null = null;
    // eslint-disable-next-line no-cond-assign
    while ((match = regex.exec(text)) !== null) {
      last = match[1].trim();
    }
    if (!last) return null;
    const firstToken = last.split(/\s+/)[0]?.toUpperCase() ?? '';
    const readOnlyVerbs = new Set(['SELECT', 'SHOW', 'DESCRIBE', 'EXPLAIN', 'WITH', 'PRAGMA']);
    if (readOnlyVerbs.has(firstToken)) {
      return null;
    }
    return last;
  };

  // Extract Excel export info (base64 or simple text sentence)
  const extractExportData = (text: string): ExportData | null => {
    // 1. Preferred: new format with base64 data from database_agent
    const base64Match = text.match(/\[EXCEL_BASE64_START\]([\s\S]*?)\[EXCEL_BASE64_END\]/);
    const filenameMatch = text.match(/\[FILENAME_START\]([\s\S]*?)\[FILENAME_END\]/);
    const rowCountMatch = text.match(/\[ROW_COUNT_START\](\d+)\[ROW_COUNT_END\]/);

    if (base64Match && filenameMatch) {
      return {
        base64: base64Match[1].trim(),
        filename: filenameMatch[1].trim(),
        rowCount: rowCountMatch ? parseInt(rowCountMatch[1], 10) : 0,
      };
    }
    return null;
  };

  const canSend = useMemo(() => {
    const hasText = query.trim().length > 0;
    const hasAttachment = attachedExcel != null;
    return !isLoading && !isUploadingExcel && (hasText || hasAttachment);
  }, [isLoading, isUploadingExcel, query, attachedExcel]);

  const handleExcelFileSelected = async (file: File) => {
    setIsUploadingExcel(true);
    try {
      const res = await uploadExcel(file, sessionId, selectedProject?.id || null);
      if (!res.success) {
        window.alert(res.error || 'Failed to upload Excel file');
        return;
      }
      setAttachedExcel({
        originalName: res.file.original_name,
        serverPath: res.file.server_path,
        sizeBytes: res.file.size_bytes,
      });
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
    // allow re-selecting same file
    e.target.value = '';
    if (!file) return;
    void handleExcelFileSelected(file);
  };

  // Load session when sessionId from URL (propSessionId) is set. Must run when URL has
  // a session (e.g. /chat/87c3eb73) including on full reload, so we load whenever
  // propSessionId is present — not only when it differs from state (on reload state
  // is initialized from the same prop, so propSessionId === sessionId and we'd skip loading).
  useEffect(() => {
    const loadSession = async (sid: string) => {
      try {
        setIsLoading(true);
        const res = await getSession(sid);
        if (res.success && res.messages) {
          const convertedMessages: UiMessage[] = res.messages
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            .filter((msg: any) => msg.role === 'user' || msg.role === 'assistant')
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            .map((msg: any) => ({
              text: msg.content || '',
              isUser: msg.role === 'user',
              sqlToExecute: msg.role === 'assistant' ? extractLastMutationSqlBlock(msg.content || '') : null,
              exportToExcel: msg.role === 'assistant' ? extractExportData(msg.content || '') : null,
            }));
          setMessages(convertedMessages);
          setSessionId(sid);
          onSessionIdChange?.(sid);
          saveLastSession(sid, selectedProject?.id ?? null);
        }
      } catch (err) {
        console.error('Failed to load session:', err);
        window.alert('Failed to load chat history');
      } finally {
        setIsLoading(false);
      }
    };

    if (propSessionId) {
      void loadSession(propSessionId);
    } else if (sessionId) {
      // URL no longer has a session (e.g. navigated to /chat) — clear local state
      setMessages([]);
      setSessionId(null);
      onSessionIdChange?.(null);
      saveLastSession(null, null);
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
    console.log('Sending message with sessionId:', sessionId);
    console.log('Selected project:', selectedProject);
    try {
      const res = await sendMessage(text, sessionId, selectedProject?.id || null);
      if (res.success) {
        setMessages((prev) => [
          ...prev,
          {
            text: res.response,
            isUser: false,
            sqlToExecute: extractLastMutationSqlBlock(res.response),
            exportToExcel: extractExportData(res.response),
          },
        ]);
        
        if (res.session_id) {
          const newSessionId = res.session_id;
          const isNewSession = sessionId !== newSessionId;
          console.log('Response sessionId:', newSessionId, 'isNewSession:', isNewSession);

          setSessionId(newSessionId);
          onSessionIdChange?.(newSessionId);
          saveLastSession(newSessionId, selectedProject?.id ?? null);

          // Update URL so /chat becomes /chat/:sessionId (or /chat/:projectId/:sessionId)
          if (selectedProject?.id) {
            window.history.pushState({}, '', `/chat/${selectedProject.id}/${newSessionId}`);
          } else {
            window.history.pushState({}, '', `/chat/${newSessionId}`);
          }
          window.dispatchEvent(new PopStateEvent('popstate'));

          // Reload project sessions to update the history UI
          if (isNewSession) {
            setTimeout(() => {
              void loadProjectSessions();
            }, 500);
          }
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
    if (isLoading || isUploadingExcel) return;
    const hasText = query.trim().length > 0;
    if (!hasText && !attachedExcel) return;

    const displayText = hasText ? query.trim() : `Uploaded Excel: ${attachedExcel?.originalName ?? ''}`.trim();
    let sendText = displayText;
    if (attachedExcel) {
      const prompt =
        hasText && displayText
          ? displayText
          : `Hãy đọc và tóm tắt file Excel "${attachedExcel.originalName}".`;
      sendText =
        `${prompt}\n\n` +
        `[UPLOADED_EXCEL_PATH_START]\n${attachedExcel.serverPath}\n[UPLOADED_EXCEL_PATH_END]\n` +
        `[UPLOADED_EXCEL_NAME_START]\n${attachedExcel.originalName}\n[UPLOADED_EXCEL_NAME_END]\n`;
    }

    setMessages((prev) => [...prev, { text: displayText, isUser: true }]);
    setQuery('');
    // Forcefully reset the textarea to avoid any IME/browser ghost text by
    // both clearing state and remounting the textarea component.
    setInputKey((k) => k + 1);
    await doSend(sendText);
    if (attachedExcel) setAttachedExcel(null);
  };

  const handleRefreshResponse = async (aiIndex: number) => {
    const userIndex = aiIndex - 1;
    if (userIndex < 0) return;
    const userMsg = messages[userIndex];
    if (!userMsg?.isUser) return;

    setIsLoading(true);
    try {
      const res = await sendMessage(userMsg.text, sessionId, selectedProject?.id || null);
      if (res.success) {
        setMessages((prev) => {
          const updated = [...prev];
          updated[aiIndex] = {
            text: res.response,
            isUser: false,
            sqlToExecute: extractLastMutationSqlBlock(res.response),
            exportToExcel: extractExportData(res.response),
          };
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

  const handleExecuteSql = async (aiIndex: number) => {
    const msg = messages[aiIndex];
    if (!msg || !msg.sqlToExecute || isLoading) return;

    // Detect language from user's last message
    const userMessages = messages.filter(m => m.isUser);
    const lastUserMsg = userMessages[userMessages.length - 1];
    const lang = lastUserMsg ? detectLanguage(lastUserMsg.text) : 'en';

    setIsLoading(true);
    try {
      const res = await executeSql(msg.sqlToExecute, sessionId, selectedProject?.id || null, lang);
      if (res.success) {
        setMessages((prev) => {
          const updated = [...prev];
          const current = updated[aiIndex];
          if (current) {
            // Clear sqlToExecute on the preview message so Execute SQL cannot be clicked again
            updated[aiIndex] = { ...current, sqlToExecute: null };
          }
          return [
            ...updated,
            {
              text: res.response,
              isUser: false,
              sqlToExecute: extractLastMutationSqlBlock(res.response),
              exportToExcel: extractExportData(res.response),
            },
          ];
        });
      } else {
        setMessages((prev) => [
          ...prev,
          { text: `Error: ${res.error || 'Failed to execute SQL'}`, isUser: false },
        ]);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to execute SQL';
      setMessages((prev) => [...prev, { text: `Error: ${message}`, isUser: false }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleExportExcel = async (aiIndex: number) => {
    const msg = messages[aiIndex];
    if (!msg || !msg.exportToExcel || isLoading) return;

    setIsLoading(true);
    try {
      const exportDataObj = msg.exportToExcel;

      if (exportDataObj.base64) {
        // New flow: download directly from base64
        const byteCharacters = atob(exportDataObj.base64);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
          byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = exportDataObj.filename || 'export.xlsx';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
      }

      setMessages((prev) => {
        const updated = [...prev];
        const current = updated[aiIndex];
        if (current) {
          // Clear exportToExcel so button disappears after download
          updated[aiIndex] = { ...current, exportToExcel: null };
        }
        return updated;
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to export';
      setMessages((prev) => [...prev, { text: `Error: ${message}`, isUser: false }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCancelSql = (aiIndex: number) => {
    const msg = messages[aiIndex];
    if (!msg || !msg.sqlToExecute) return;
    // Simply clear the sqlToExecute flag so the Execute button disappears.
    setMessages((prev) => {
      const updated = [...prev];
      updated[aiIndex] = { ...msg, sqlToExecute: null };
      return updated;
    });
  };

  // When switching to a *different* project: save current session for the project we're leaving, then clear UI.
  // This way when user comes back to that project, we restore the session instead of creating a new one (no duplicate history).
  const prevProjectIdRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    const currentId = selectedProject?.id;
    if (prevProjectIdRef.current !== undefined && prevProjectIdRef.current !== currentId) {
      saveLastSession(sessionId, prevProjectIdRef.current ?? null);
      setSessionId(null);
      setMessages([]);
      onSessionIdChange?.(null);
    }
    prevProjectIdRef.current = currentId;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProject?.id]);

  // Function to load project sessions
  const loadProjectSessions = async () => {
    if (!selectedProject) {
      setProjectSessions([]);
      setSessionPreviews({});
      return;
    }

    console.log('Loading sessions for project:', selectedProject.name, selectedProject.id);
    try {
      // Get sessions filtered by project_id from backend
      const res = await getSessions(selectedProject.id);
      if (res.success) {
        const list = res.sessions ?? [];
        const seen = new Set<string>();
        const unique = list.filter((s) => {
          if (seen.has(s.session_id)) return false;
          seen.add(s.session_id);
          return true;
        });
        setProjectSessions(unique);

        // Load preview for each session (first user message)
        const previews: Record<string, string> = {};
        for (const session of unique) {
          try {
            const sessionRes = await getSession(session.session_id);
            if (sessionRes.success && sessionRes.messages) {
              const firstUserMessage = sessionRes.messages.find((msg: any) => msg.role === 'user') as { content?: string } | undefined;
              if (firstUserMessage && firstUserMessage.content) {
                previews[session.session_id] = firstUserMessage.content;
              }
            }
          } catch (err) {
            console.error(`Failed to load preview for session ${session.session_id}:`, err);
          }
        }
        setSessionPreviews(previews);
      }
    } catch (err) {
      console.error('Failed to load project sessions:', err);
    }
  };

  // Restore last session from localStorage on mount/reload (don't create a new session every time)
  useEffect(() => {
    if (propSessionId != null || hasRestoredSessionRef.current) return;
    const last = getLastSession(selectedProject?.id ?? null);
    if (!last) return;
    hasRestoredSessionRef.current = true;
    const loadSession = async (sid: string) => {
      try {
        setIsLoading(true);
        const res = await getSession(sid);
        if (res.success && res.messages) {
          const convertedMessages: UiMessage[] = res.messages
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            .filter((msg: any) => msg.role === 'user' || msg.role === 'assistant')
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            .map((msg: any) => ({
              text: msg.content || '',
              isUser: msg.role === 'user',
              sqlToExecute: msg.role === 'assistant' ? extractLastMutationSqlBlock(msg.content || '') : null,
              exportToExcel: msg.role === 'assistant' ? extractExportData(msg.content || '') : null,
            }));
          setMessages(convertedMessages);
          setSessionId(sid);
          onSessionIdChange?.(sid);
        }
      } catch {
        hasRestoredSessionRef.current = false;
      } finally {
        setIsLoading(false);
      }
    };
    void loadSession(last);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProject?.id, propSessionId]);

  // Load project sessions only when project *id* changes (not on every selectedProject object reference change, e.g. from 500ms poll)
  useEffect(() => {
    void loadProjectSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProject?.id]);

  // Format session name
  const formatSessionName = (session: SessionInfo): string => {
    if (session.session_name && session.session_name !== `Session ${session.session_id}`) {
      return session.session_name;
    }
    return 'New chat';
  };

  // Format date
  const formatDate = (dateString?: string): string => {
    if (!dateString) return '';
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch {
      return '';
    }
  };

  // Check if project has chat history
  const projectHasHistory = selectedProject && projectSessions.length > 0 && !sessionId && messages.length === 0;

  // Check if we're in "empty" state: no messages (regardless of project or sessionId)
  // This includes: 
  // - Project selected but no chat history yet (show empty state with project in header)
  // - No project and no chat
  // - New session created but no messages sent yet
  const isEmptyState = messages.length === 0 && !projectHasHistory;

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Chat Content */}
      {messages.length > 0 && (
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="max-w-5xl mx-auto w-full">
            <MessageList
              messages={messages}
              onRefreshResponse={(idx) => void handleRefreshResponse(idx)}
              onExecuteSql={(idx) => void handleExecuteSql(idx)}
              onCancelSql={(idx) => void handleCancelSql(idx)}
              onExportExcel={(idx) => void handleExportExcel(idx)}
            />
            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      {/* Input Field - Fixed position, same position whether empty or has history */}
      <div className={`flex flex-col pb-10 pt-10 ${isEmptyState ? "justify-center flex-1 " : "justify-start pt-50"}`}>
        <div className="max-w-5xl mx-auto w-full">
          {/* Greeting text - Show in empty state or when project has history */}
          {(isEmptyState || projectHasHistory) && (
            <div className="text-center mb-6">
              <h2 className="text-5xl md:text-6xl font-bold text-gray-900">Hi, How are you today?</h2>
            </div>
          )}
          <div className="relative bg-white border-2 border-gray-300 rounded-3xl px-4 shadow-lg">
            <div className="flex flex-col">
              {(attachedExcel || isUploadingExcel) && (
                <div className="flex items-center gap-2 pt-3 pb-1">
                  {isUploadingExcel && (
                    <span className="text-xs text-gray-500">Uploading…</span>
                  )}
                  {attachedExcel && (
                    <>
                      <span className="inline-flex items-center gap-2 text-xs bg-gray-100 text-gray-700 px-3 py-1 rounded-full">
                        <img src={fileIcon} alt="" className="w-4 h-4" />
                        <span className="max-w-[240px] truncate">{attachedExcel.originalName}</span>
                      </span>
                      <button
                        type="button"
                        onClick={() => setAttachedExcel(null)}
                        className="text-xs text-gray-500 hover:text-gray-700"
                      >
                        Remove
                      </button>
                    </>
                  )}
                </div>
              )}

              <div className="flex items-center gap-3 min-h-[48px]">
                <div className="relative flex-shrink-0">
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="text-gray-500 hover:text-gray-700 transition-colors"
                    aria-label="Attach file"
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
                </div>

                <textarea
                  key={inputKey}
                  ref={textareaRef}
                  value={query}
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                    setQuery(e.target.value)
                  }
                  onKeyDown={(e: React.KeyboardEvent<HTMLTextAreaElement>) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void handleSend();
                    }
                  }}
                  placeholder={
                    selectedProject
                      ? `New chat in ${selectedProject.name}`
                      : "Ask anything"
                  }
                  rows={1}
                  autoComplete="off"
                  autoCorrect="off"
                  spellCheck={false}
                  className="flex-1 resize-none outline-none text-lg"
                  style={{
                    maxHeight: `${MAX_TEXTAREA_HEIGHT}px`,
                    minHeight: "60px",
                    paddingTop: "20px",
                    paddingBottom: "20px",
                  }}
                />

                <div className="flex items-center gap-2 flex-shrink-0">
                  <button type="button" onClick={(): void => {}} aria-label="Microphone">
                    <img src={microphoneIcon} alt="Microphone" className="w-5 h-5" />
                  </button>
                  <button
                    type="button"
                    onClick={(): void => { void handleSend(); }}
                    disabled={!canSend}
                    className="flex items-center justify-center w-10 h-10 rounded-full p-0 opacity-60 hover:opacity-100 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
                    aria-label="Send"
                  >
                    <img src={arrowUpCircleIcon} alt="" className="w-20 h-20" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Project Chat History - Show when project has history, right below chatbox */}
      {
        projectHasHistory && (
          <div className="flex-1 overflow-y-auto px-8 pb-8 border-2 border-green-500">
            <div className="max-w-4xl mx-auto">
              <div className="space-y-0">
                {projectSessions.map((session, index) => (
                  <div key={session.session_id}>
                    {index > 0 && <div className="border-t border-gray-200"></div>}
                    <button
                      onClick={() => {
                        // Navigate to project session URL
                        if (selectedProject) {
                          window.history.pushState({}, '', `/chat/${selectedProject.id}/${session.session_id}`);
                          window.dispatchEvent(new PopStateEvent('popstate'));
                        } else {
                          // Fallback: navigate to unassigned session
                          window.history.pushState({}, '', `/chat/${session.session_id}`);
                          window.dispatchEvent(new PopStateEvent('popstate'));
                        }
                        if (onSessionIdChange) {
                          onSessionIdChange(session.session_id);
                        }
                      }}
                      className="w-full text-left py-4 hover:bg-gray-50 transition-colors"
                      type="button"
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <h3 className="font-semibold text-gray-900 mb-1">{formatSessionName(session)}</h3>
                          {sessionPreviews[session.session_id] && (
                            <p className="text-sm text-gray-600 truncate">{sessionPreviews[session.session_id]}</p>
                          )}
                        </div>
                        {session.created_at && (
                          <span className="text-xs text-gray-500 ml-4 flex-shrink-0">
                            {formatDate(session.created_at)}
                          </span>
                        )}
                      </div>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )
      }

      {/* Disclaimer - Only show in empty state */}
      {
        isEmptyState && (
          <div className="px-8 pb-8">
            <div className="max-w-4xl mx-auto">
              <p className="text-center text-xs text-gray-500">
              By using LightDBee, you agree to our Term and Service Policy
              </p>
            </div>
          </div>
        )
      }

    </div >
  );
}

