import React, { useEffect, useMemo, useRef, useState } from 'react';
import MessageList, { type UiMessage, type SchemaPreviewData } from '../components/chat/MessageList';
import {
  getSession,
  sendMessageWithStream,
  getSessions,
  executeSql,
  resumeWorkflow,
  createSession,
  listUserFilesInventory,
  uploadSessionFile,
  deleteSessionFile,
  downloadStoredSessionFile,
  type SessionInfo,
  type SessionShareInfo,
  type ToolEvent,
  type GetSessionResponse,
} from '../services/api';
import {
  buildChatMessageWithSessionFiles,
  extractSessionFileAttachments,
  stripSessionFileMarkers,
} from '../utils/sessionFileMarkers';
import {
  extractExportData,
  stripExcelMarkersFromText,
  triggerExcelDownload,
} from '../utils/excelExportMarkers';
import plusIcon from '../assets/icons/Plus.svg';
import fileIcon from '../assets/icons/File.svg';
import microphoneIcon from '../assets/icons/Microphone.svg';
import arrowUpCircleIcon from '../assets/icons/Arrow-up-circle.svg';
import stopCircleIcon from '../assets/icons/Stop_circle.svg';

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
  const [shareInfo, setShareInfo] = useState<SessionShareInfo | null>(null);
  const [selectedProject, setSelectedProject] = useState<{ id: string; name: string } | null>(null);
  const [projectSessions, setProjectSessions] = useState<SessionInfo[]>([]);
  const [sessionPreviews, setSessionPreviews] = useState<Record<string, string>>({});
  const [inputKey, setInputKey] = useState(0);
  const previousProjectIdRef = useRef<string | null>(null);
  const hasRestoredSessionRef = useRef(false);
  const previousPropSessionIdRef = useRef<string | null | undefined>(undefined);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [isUploadingExcel, setIsUploadingExcel] = useState(false);
  /** Session files staged above the textarea until the user sends (Enter). */
  const [inputAttachedFiles, setInputAttachedFiles] = useState<{ id: string; filename: string }[]>([]);
  const [isAssistantTyping, setIsAssistantTyping] = useState(false);
  const [typingStopSignal, setTypingStopSignal] = useState(0);
  // Live progress label streamed from the backend (e.g. "Đang sinh SQL...").
  // Null when no streaming chat is in flight.
  const [streamingStage, setStreamingStage] = useState<string | null>(null);
  const sendAbortControllerRef = useRef<AbortController | null>(null);

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

  const hashString = (input: string): string => {
    let hash = 0;
    for (let i = 0; i < input.length; i += 1) {
      hash = ((hash << 5) - hash + input.charCodeAt(i)) | 0;
    }
    return Math.abs(hash).toString(36);
  };

  const buildSqlActionId = (
    sid: string | null,
    messageContent: string,
    sqlText: string,
    sqlOrdinal: number,
  ): string => {
    const base = `${sid ?? 'nosession'}|${sqlOrdinal}|${messageContent}|${sqlText}`;
    return `sqlact_${hashString(base)}`;
  };

  const extractLastMutationSqlBlock = (text: string): string | null => {
    // Allow optional space/newline after language tag: ```sql or ``` sql
    const regex = /```\s*sql\s*([\s\S]*?)```/gi;
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

  const extractSchemaPreviewFromToolEvents = (events?: ToolEvent[]): SchemaPreviewData | null => {
    if (!events || !Array.isArray(events)) return null;

    const schemaEvent = events.find(
      (e) => e?.tool === 'show_create_table_schema' && e?.type === 'schema_preview' && e?.payload
    );
    if (!schemaEvent?.payload) return null;

    const payload = schemaEvent.payload as Record<string, any>;
    const tableName = payload.tableName || payload.table_name;
    const primaryKey = payload.primaryKey ?? payload.primary_key ?? null;
    const columnsRaw = Array.isArray(payload.columns) ? payload.columns : [];
    const columns = columnsRaw
      .map((c: any) => ({ variable: c?.variable, type: c?.type }))
      .filter((c: any) => c.variable && c.type);

    if (!tableName || columns.length === 0) return null;
    return { tableName, primaryKey, columns };
  };

  type SqlPreviewData = {
    sql: string;
    mutationPreviewMarkdown?: string | null;
  };

  const extractSqlPreviewFromToolEvents = (events?: ToolEvent[]): SqlPreviewData | null => {
    if (!events || !Array.isArray(events)) return null;
    const sqlEvent = events.find((e) => e?.type === 'sql_preview' && e?.payload);
    if (!sqlEvent?.payload) return null;
    const payload = sqlEvent.payload as Record<string, any>;
    const sql = typeof payload.sql === 'string' ? payload.sql.trim() : '';
    if (!sql) return null;
    const mutationPreviewMarkdown =
      typeof payload.mutation_preview_markdown === 'string'
        ? payload.mutation_preview_markdown.trim()
        : typeof payload.mutationPreviewMarkdown === 'string'
          ? payload.mutationPreviewMarkdown.trim()
          : null;
    return { sql, mutationPreviewMarkdown };
  };

  const buildAssistantTextFromSqlPreview = (
    cleanedText: string,
    sqlPreview: SqlPreviewData | null,
  ): string => {
    if (!sqlPreview) return cleanedText;
    // Prefer tool_events over parsing assistant text. Append a stable SQL fenced block
    // so ChatMessage can render it as markdown.
    const hasSqlFence = /```\s*sql/i.test(cleanedText);
    const parts: string[] = [];
    if (cleanedText.trim().length > 0) parts.push(cleanedText.trim());
    if (!hasSqlFence) parts.push(`\`\`\`sql\n${sqlPreview.sql}\n\`\`\``);
    // Do NOT append mutationPreviewMarkdown here:
    // - Backend may already include it in message text
    // - ChatMessage will render markdown from text, so we'd duplicate the preview
    // If we want a dedicated preview UI, render from tool_events as a separate component instead.
    return parts.join('\n\n').trim();
  };

  const extractSchemaPreview = (text: string): SchemaPreviewData | null => {
    // Preferred path: structured JSON payload from show_create_table_schema tool output.
    const jsonMatch = text.match(/\[CREATE_TABLE_SCHEMA_JSON_START\]([\s\S]*?)\[CREATE_TABLE_SCHEMA_JSON_END\]/);
    if (jsonMatch) {
      try {
        const parsed = JSON.parse(jsonMatch[1].trim()) as SchemaPreviewData;
        if (!parsed?.tableName && (parsed as any).table_name) {
          return {
            tableName: (parsed as any).table_name,
            primaryKey: (parsed as any).primary_key ?? null,
            columns: Array.isArray((parsed as any).columns) ? (parsed as any).columns : [],
          };
        }
        return parsed;
      } catch {
        // continue to marker-based fallback
      }
    }

    // Fallback for cases where agent called the tool but did not preserve JSON payload.
    // Accept markdown Variable|Type table when message looks like create-table schema review.
    const looksLikeSchemaReview =
      text.includes('[CREATE_TABLE_SCHEMA_PREVIEW]') ||
      /schema\s+đề\s+xuất\s+cho\s+bảng/i.test(text) ||
      /proposed\s+schema\s+for\s+table/i.test(text) ||
      /\bcreate_table\b/i.test(text) ||
      /\bcreate table\b/i.test(text);

    if (!looksLikeSchemaReview) return null;

    const lines = text.split('\n').map((l) => l.trim());
    const tableStart = lines.findIndex((l) => /^\|\s*Variable\s*\|\s*Type\s*\|$/i.test(l));
    if (tableStart === -1) return null;

    const columns: Array<{ variable: string; type: string }> = [];
    for (let i = tableStart + 1; i < lines.length; i += 1) {
      const line = lines[i];
      if (!line.startsWith('|')) break;
      if (/^\|\s*-+\s*\|\s*-+\s*\|$/.test(line.replace(/:/g, ''))) continue;

      const cells = line
        .split('|')
        .map((c) => c.trim())
        .filter((_, idx, arr) => !(idx === 0 || idx === arr.length - 1));

      if (cells.length < 2) continue;
      const variable = cells[0].replace(/^`|`$/g, '');
      const type = cells[1].replace(/^`|`$/g, '');
      if (variable && type) columns.push({ variable, type });
    }

    if (columns.length === 0) return null;

    const tableNameMatch =
      text.match(/Proposed table:\s*`([^`]+)`/i) ||
      text.match(/table\s+`([^`]+)`/i) ||
      text.match(/bảng\s+`([^`]+)`/i);
    const tableName = tableNameMatch?.[1] || 'new_table';

    return {
      tableName,
      primaryKey: null,
      columns,
    };
  };

  const getSqlActionStatesFromSessionResponse = (res: GetSessionResponse): Record<string, 'pending' | 'running' | 'executed' | 'cancelled'> => {
    if (!res.success) return {};
    const raw = (res.session_info as any)?.sql_action_states;
    if (!raw || typeof raw !== 'object') return {};
    const out: Record<string, 'pending' | 'running' | 'executed' | 'cancelled'> = {};
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      const value = String(v || '').toLowerCase();
      if (value === 'pending' || value === 'running' || value === 'executed' || value === 'cancelled') {
        out[String(k)] = value;
      }
    }
    return out;
  };

  const extractSqlActionId = (text: string): string | undefined => {
    const m = text.match(/\[SQL_ACTION_ID_START\]([\s\S]*?)\[SQL_ACTION_ID_END\]/);
    const id = m?.[1]?.trim();
    return id || undefined;
  };

  const extractUploadAttachments = extractSessionFileAttachments;

  const stripInternalPayloads = (text: string): string => {
    let cleaned = stripSessionFileMarkers(
      text
        .replace(/\n?\[CREATE_TABLE_SCHEMA_JSON_START\][\s\S]*?\[CREATE_TABLE_SCHEMA_JSON_END\]\n?/g, '\n')
        .replace(/\n?\[SCHEMA_CONFIRM_INTERNAL_START\][\s\S]*?\[SCHEMA_CONFIRM_INTERNAL_END\]\n?/g, '\n')
        // Legacy Superset chart-embed markers — Superset has been removed but old
        // assistant messages still carry them; strip so they don't render as raw text.
        .replace(/\n?\[CHART_EMBED_URL_START\][\s\S]*?\[CHART_EMBED_URL_END\]\n?/g, '\n')
        .replace(/\n?\[CHART_EMBED_META_START\][\s\S]*?\[CHART_EMBED_META_END\]\n?/g, '\n')
        // File path markers for the agent; name/id handled in stripSessionFileMarkers
        .replace(/\n?\[UPLOADED_EXCEL_PATH_START\][\s\S]*?\[UPLOADED_EXCEL_PATH_END\]\n?/g, '\n'),
    );

    // Strip the read-only-share system note that older builds accidentally
    // persisted into the user's message history.
    cleaned = cleaned.replace(
      /^\[SHARED SESSION\s*[—-]\s*READ-ONLY MODE\][\s\S]*?\n\s*User message:\s*/i,
      '',
    );

    // Hide backend internal execution prompts from history display
    if (/^User has confirmed schema\./i.test(cleaned.trim()) && /User request:/i.test(cleaned)) {
      const reqMatch = cleaned.match(/User request:\s*(.+)$/im);
      if (reqMatch?.[1]) {
        return reqMatch[1].trim();
      }
    }

    // Hide internal schema-discovery prompt generated by workflow
    if (/^Show me the schema for tables:/i.test(cleaned.trim()) && /Use list_tables and describe_table tools\.?$/i.test(cleaned.trim())) {
      return '';
    }

    // Hide legacy wrapper text like "Generate SQL for: ... Show the SQL but do NOT execute it."
    cleaned = cleaned.replace(/^Generate SQL for:\s*/i, '');
    cleaned = cleaned.replace(/\.?\s*Show the SQL but do NOT execute it\.?\s*$/i, '');

    // Hide internal schema-tool forcing prompt if it leaks to UI.
    if (/^You MUST call tool `show_create_table_schema`/i.test(cleaned.trim())) {
      const reqMatch = cleaned.match(/User request:\s*(.+)$/im);
      if (reqMatch?.[1]) {
        return reqMatch[1].trim();
      }
      return '';
    }

    cleaned = cleaned.replace(/^\[CREATE_TABLE_SCHEMA_PREVIEW\]\s*/i, '');
    cleaned = cleaned.replace(/\n?\[SQL_ACTION_ID_START\][\s\S]*?\[SQL_ACTION_ID_END\]\n?/g, '\n');
    cleaned = stripExcelMarkersFromText(cleaned);

    return cleaned.trim();
  };

  const isStopVisible = isLoading || isAssistantTyping;

  const isViewOnlyShare = shareInfo?.permission === 'view_only' || shareInfo?.revoked === true;

  const canSend = useMemo(() => {
    // ChatGPT-style: an attachment alone is not enough — the user must type
    // what they want to do with it. The Send button stays disabled until
    // there's actual text in the textarea.
    const hasText = query.trim().length > 0;
    if (isViewOnlyShare) return false;
    return !isStopVisible && !isUploadingExcel && hasText;
  }, [isStopVisible, isUploadingExcel, query, isViewOnlyShare]);

  const handleRemoveInputAttachment = async (fileId: string) => {
    try {
      await deleteSessionFile(fileId);
      setInputAttachedFiles((prev) => prev.filter((f) => f.id !== fileId));
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Remove failed');
    }
  };

  const handleExcelFileSelected = async (file: File) => {
    setIsUploadingExcel(true);
    try {
      let sid = sessionId;
      if (!sid) {
        const cr = await createSession(null, selectedProject?.id || propProjectId || null);
        if (!cr.success || !cr.session_id) {
          window.alert('Could not create a chat session for this upload');
          return;
        }
        sid = cr.session_id;
        setSessionId(sid);
        onSessionIdChange?.(sid);
        saveLastSession(sid, selectedProject?.id ?? propProjectId ?? null);
        if (selectedProject?.id || propProjectId) {
          window.history.pushState({}, '', `/chat/${selectedProject?.id || propProjectId}/${sid}`);
        } else {
          window.history.pushState({}, '', `/chat/${sid}`);
        }
        window.dispatchEvent(new PopStateEvent('popstate'));
      }
      const { file: uploaded } = await uploadSessionFile(sid!, file, selectedProject?.id || propProjectId || null);
      setInputAttachedFiles((prev) => [...prev, { id: uploaded.id, filename: uploaded.filename }]);
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
            'Bạn đã dùng hết 5 GB dung lượng lưu trữ cho file đã tải. Hãy xóa bớt file (dấu × trên chip ở ô nhập hoặc trong mục Lưu trữ) rồi thử lại.\n\n' +
              (lines.length ? `Một số file gần đây:\n${lines.join('\n')}` : ''),
          );
        } catch {
          window.alert(
            'Bạn đã dùng hết 5 GB dung lượng lưu trữ. Hãy xóa file (dấu × trên chip ở ô nhập hoặc trong mục Lưu trữ) rồi thử lại.',
          );
        }
      } else {
        window.alert(e instanceof Error ? e.message : 'Failed to upload file');
      }
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
          const sqlActionStates = getSqlActionStatesFromSessionResponse(res);
          let sqlOrdinal = 0;
          const convertedMessages: UiMessage[] = res.messages
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            .filter((msg: any) => msg.role === 'user' || msg.role === 'assistant')
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            .map((msg: any) => {
              const rawContent = msg.content || '';
              const cleanedText = stripInternalPayloads(rawContent);
              const sqlPreview =
                msg.role === 'assistant' ? extractSqlPreviewFromToolEvents((msg as any).tool_events) : null;
              const schemaPreview =
                msg.role === 'assistant'
                  ? extractSchemaPreviewFromToolEvents((msg as any).tool_events) || extractSchemaPreview(rawContent)
                  : null;
              const sqlToExecute =
                msg.role === 'assistant'
                  ? (sqlPreview?.sql || extractLastMutationSqlBlock(rawContent))
                  : null;
              const markerActionId = msg.role === 'assistant' ? extractSqlActionId(rawContent) : undefined;
              const sqlActionId = sqlToExecute ? (markerActionId || buildSqlActionId(sid, cleanedText, sqlToExecute, sqlOrdinal++)) : undefined;
              const persistedSqlState = sqlActionId ? sqlActionStates[sqlActionId] : undefined;
              return {
                text: msg.role === 'assistant' ? buildAssistantTextFromSqlPreview(cleanedText, sqlPreview) : cleanedText,
                isUser: msg.role === 'user',
                attachments: msg.role === 'user' ? extractUploadAttachments(rawContent) : undefined,
                sqlToExecute,
                sqlActionId,
                sqlActionState: sqlToExecute ? (persistedSqlState ?? ('pending' as const)) : undefined,
                exportToExcel: msg.role === 'assistant' ? extractExportData(rawContent) : null,
                schemaPreview,
                schemaLocked: msg.role === 'assistant' ? !!schemaPreview : undefined,
              };
            })
            .filter((m) => m.text.trim().length > 0 || !!m.schemaPreview || !!m.sqlToExecute || !!m.exportToExcel || (m.attachments && m.attachments.length > 0));
          setMessages(convertedMessages);
          setInputAttachedFiles([]);
          setSessionId(sid);
          setShareInfo(res.share_info ?? null);
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

    const prevPropSessionId = previousPropSessionIdRef.current;
    previousPropSessionIdRef.current = propSessionId;

    if (propSessionId) {
      void loadSession(propSessionId);
      return;
    }

    const sessionWasExplicitlyRemoved = prevPropSessionId != null;
    if (sessionWasExplicitlyRemoved && sessionId) {
      // URL no longer has a session (e.g. navigated to /chat) — clear local state
      setMessages([]);
      setInputAttachedFiles([]);
      setSessionId(null);
      setShareInfo(null);
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
    setIsAssistantTyping(false);
    setStreamingStage('Processing...');
    const controller = new AbortController();
    sendAbortControllerRef.current = controller;
    console.log('Sending message with sessionId:', sessionId);
    console.log('Selected project:', selectedProject);
    try {
      const finalRes = await sendMessageWithStream(text, sessionId, selectedProject?.id || null, {
        onStage: (m) => setStreamingStage(m),
        signal: controller.signal,
      });
      setStreamingStage(null);
      // ChatResponse is a discriminated union; downstream code reads optional
      // tool_events / pending_workflow_resume that only exist on success. Keep
      // the original behaviour of treating the payload as a loose object.
      const res = finalRes as any;
      if (res.response && res.response.trim().length > 0) {
        setIsAssistantTyping(true);
        setMessages((prev) => [
          ...prev,
          {
            text: buildAssistantTextFromSqlPreview(
              stripInternalPayloads(res.response),
              extractSqlPreviewFromToolEvents((res as any).tool_events),
            ),
            isUser: false,
            sqlToExecute: extractSqlPreviewFromToolEvents((res as any).tool_events)?.sql || extractLastMutationSqlBlock(res.response),
            sqlActionId: extractSqlActionId(res.response),
            sqlActionState:
              (extractSqlPreviewFromToolEvents((res as any).tool_events)?.sql || extractLastMutationSqlBlock(res.response))
                ? ('pending' as const)
                : undefined,
            exportToExcel: extractExportData(res.response),
            schemaPreview: extractSchemaPreviewFromToolEvents((res as any).tool_events) || extractSchemaPreview(res.response),
            schemaLocked: false,
            workflowResumePending: !!(res as { pending_workflow_resume?: boolean }).pending_workflow_resume,
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
      } else if (!res.success) {
        setIsAssistantTyping(false);
        setMessages((prev) => [...prev, { text: `Error: ${res.error || 'Failed to get response'}`, isUser: false }]);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
      setIsAssistantTyping(false);
      setStreamingStage(null);
      const message = err instanceof Error ? err.message : 'Failed to connect to server';
      setMessages((prev) => [...prev, { text: `Error: ${message}`, isUser: false }]);
    } finally {
      sendAbortControllerRef.current = null;
      setIsLoading(false);
      setStreamingStage(null);
    }
  };

  const handleStopResponse = () => {
    if (sendAbortControllerRef.current) {
      sendAbortControllerRef.current.abort();
      sendAbortControllerRef.current = null;
    }
    if (isAssistantTyping) {
      setTypingStopSignal((prev) => prev + 1);
    }
    setIsLoading(false);
    setIsAssistantTyping(false);
    setStreamingStage(null);
  };

  const lockAllSchemaPreviews = () => {
    setMessages((prev) =>
      prev.map((m) =>
        m.schemaPreview
          ? {
              ...m,
              schemaLocked: true,
            }
          : m
      )
    );
  };

  const handleSend = async () => {
    if (isStopVisible || isUploadingExcel) return;
    const hasText = query.trim().length > 0;
    if (!hasText) return;

    const displayText = query.trim();
    const sendPayload = buildChatMessageWithSessionFiles(displayText, inputAttachedFiles);
    const attachmentsForUi = inputAttachedFiles.map((f) => ({ name: f.filename, fileId: f.id }));

    lockAllSchemaPreviews();
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
    // Forcefully reset the textarea to avoid any IME/browser ghost text by
    // both clearing state and remounting the textarea component.
    setInputKey((k) => k + 1);
    await doSend(sendPayload);
  };

  const handleRefreshResponse = async (aiIndex: number) => {
    const userIndex = aiIndex - 1;
    if (userIndex < 0) return;
    const userMsg = messages[userIndex];
    if (!userMsg?.isUser) return;

    setIsLoading(true);
    try {
      const sendPayload = buildChatMessageWithSessionFiles(
        userMsg.text,
        (userMsg.attachments || [])
          .filter((a): a is typeof a & { fileId: string } => !!a.fileId)
          .map((a) => ({ id: a.fileId, filename: a.name })),
      );
      const res = await sendMessageWithStream(sendPayload, sessionId, selectedProject?.id || null);
      const resText = res.response;
      if (resText && resText.trim().length > 0) {
        setMessages((prev) => {
          const updated = [...prev];
          updated[aiIndex] = {
            text: buildAssistantTextFromSqlPreview(
              stripInternalPayloads(resText),
              extractSqlPreviewFromToolEvents((res as any).tool_events),
            ),
            isUser: false,
            sqlToExecute: extractSqlPreviewFromToolEvents((res as any).tool_events)?.sql || extractLastMutationSqlBlock(resText),
            sqlActionId: extractSqlActionId(resText),
            sqlActionState:
              (extractSqlPreviewFromToolEvents((res as any).tool_events)?.sql || extractLastMutationSqlBlock(resText))
                ? ('pending' as const)
                : undefined,
            exportToExcel: extractExportData(resText),
            schemaPreview: extractSchemaPreviewFromToolEvents((res as any).tool_events) || extractSchemaPreview(resText),
            workflowResumePending: !!(res as { pending_workflow_resume?: boolean }).pending_workflow_resume,
          };
          return updated;
        });
      } else if (!res.success) {
        window.alert(`Error: ${res.error || 'Failed to refresh response'}`);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to refresh response';
      window.alert(`Error: ${message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSchemaTypeChange = (aiIndex: number, variable: string, nextType: string) => {
    setMessages((prev) => {
      const updated = [...prev];
      const msg = updated[aiIndex];
      if (!msg?.schemaPreview) return prev;

      updated[aiIndex] = {
        ...msg,
        schemaPreview: {
          ...msg.schemaPreview,
          columns: msg.schemaPreview.columns.map((c) =>
            c.variable === variable ? { ...c, type: nextType } : c
          ),
        },
      };
      return updated;
    });
  };

  const handleToggleSchemaOptions = (aiIndex: number, variable: string) => {
    setMessages((prev) => {
      const updated = [...prev];
      const msg = updated[aiIndex];
      if (!msg?.schemaPreview) return prev;

      updated[aiIndex] = {
        ...msg,
        schemaPreview: {
          ...msg.schemaPreview,
          columns: msg.schemaPreview.columns.map((c) =>
            c.variable === variable ? { ...c, showOptions: !c.showOptions } : c
          ),
        },
      };
      return updated;
    });
  };

  const handleSchemaOptionChange = (
    aiIndex: number,
    variable: string,
    option: 'notNull' | 'unique' | 'primaryKey' | 'defaultValue',
    value: boolean | string,
  ) => {
    setMessages((prev) => {
      const updated = [...prev];
      const msg = updated[aiIndex];
      if (!msg?.schemaPreview) return prev;

      updated[aiIndex] = {
        ...msg,
        schemaPreview: {
          ...msg.schemaPreview,
          columns: msg.schemaPreview.columns.map((c) => {
            if (c.variable !== variable) return c;
            return {
              ...c,
              [option]: value,
            };
          }),
        },
      };
      return updated;
    });
  };

  const handleConfirmSchema = async (aiIndex: number) => {
    const msg = messages[aiIndex];
    if (!msg?.schemaPreview || isLoading) return;

    setMessages((prev) => {
      const updated = [...prev];
      const current = updated[aiIndex];
      if (current?.schemaPreview) {
        updated[aiIndex] = { ...current, schemaLocked: true };
      }
      return updated;
    });

    const schema = msg.schemaPreview;

    if (!sessionId) {
      setMessages((prev) => [...prev, { text: 'Error: No session — cannot confirm schema.', isUser: false }]);
      return;
    }

    setMessages((prev) => [
      ...prev,
      { text: `Confirm schema table ${schema.tableName}`, isUser: true },
    ]);

    setIsLoading(true);
    try {
      const res = await resumeWorkflow(
        sessionId,
        true,
        selectedProject?.id || null,
        `Confirm schema table ${schema.tableName}`,
      );
      if (res.success) {
        const resText = res.response ?? '';
        setMessages((prev) => [
          ...prev,
          {
            text: buildAssistantTextFromSqlPreview(
              stripInternalPayloads(resText),
              extractSqlPreviewFromToolEvents((res as any).tool_events),
            ),
            isUser: false,
            sqlToExecute: extractSqlPreviewFromToolEvents((res as any).tool_events)?.sql || extractLastMutationSqlBlock(resText),
            sqlActionId: extractSqlActionId(resText),
            sqlActionState:
              (extractSqlPreviewFromToolEvents((res as any).tool_events)?.sql || extractLastMutationSqlBlock(resText))
                ? ('pending' as const)
                : undefined,
            exportToExcel: extractExportData(resText),
            schemaPreview: extractSchemaPreviewFromToolEvents((res as any).tool_events) || extractSchemaPreview(resText),
            workflowResumePending: !!(res as { pending_workflow_resume?: boolean }).pending_workflow_resume,
          },
        ]);

        if (res.session_id) {
          const newSessionId = res.session_id;
          setSessionId(newSessionId);
          onSessionIdChange?.(newSessionId);
          saveLastSession(newSessionId, selectedProject?.id ?? null);
          if (selectedProject?.id) {
            window.history.replaceState({}, '', `/chat/${selectedProject.id}/${newSessionId}`);
          } else {
            window.history.replaceState({}, '', `/chat/${newSessionId}`);
          }
        }
      } else {
        setMessages((prev) => [...prev, { text: `Error: ${res.error || 'Failed to confirm schema'}`, isUser: false }]);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to confirm schema';
      setMessages((prev) => [...prev, { text: `Error: ${message}`, isUser: false }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleExecuteSql = async (aiIndex: number) => {
    const msg = messages[aiIndex];
    if (!msg || !msg.sqlToExecute || isLoading || msg.sqlActionState === 'running' || msg.sqlActionState === 'executed' || msg.sqlActionState === 'cancelled') return;

    // Lock SQL actions permanently after first click (single-run behavior)
    setMessages((prev) => {
      const updated = [...prev];
      const current = updated[aiIndex];
      if (current) {
        updated[aiIndex] = { ...current, sqlActionState: 'executed' };
      }
      return updated;
    });

    // Detect language from user's last message
    const userMessages = messages.filter(m => m.isUser);
    const lastUserMsg = userMessages[userMessages.length - 1];
    const lang = lastUserMsg ? detectLanguage(lastUserMsg.text) : 'en';

    setIsLoading(true);
    try {
      const fallbackActionId =
        msg.sqlActionId || buildSqlActionId(
          sessionId,
          msg.text,
          msg.sqlToExecute,
          Math.max(0, messages.slice(0, aiIndex + 1).filter((m) => !!m.sqlToExecute).length - 1),
        );
      const res = await executeSql(msg.sqlToExecute, fallbackActionId, sessionId, selectedProject?.id || null, lang, false, null);
      if (res.success) {
        setMessages((prev) => {
          const updated = [...prev];
          const current = updated[aiIndex];
          if (current) {
            // Keep SQL preview visible but disable actions after execution
            updated[aiIndex] = { ...current, sqlActionState: 'executed' };
          }
          const resText = res.response ?? '';
          return [
            ...updated,
            {
              text: buildAssistantTextFromSqlPreview(
                stripInternalPayloads(resText),
                extractSqlPreviewFromToolEvents((res as any).tool_events),
              ),
              isUser: false,
              sqlToExecute: extractSqlPreviewFromToolEvents((res as any).tool_events)?.sql || extractLastMutationSqlBlock(resText),
              sqlActionId: extractSqlActionId(resText),
              exportToExcel: extractExportData(resText),
              schemaPreview: extractSchemaPreviewFromToolEvents((res as any).tool_events) || extractSchemaPreview(resText),
                workflowResumePending: !!(res as { pending_workflow_resume?: boolean }).pending_workflow_resume,
            },
          ];
        });

        if ((res as any).session_id) {
          const newSessionId = (res as any).session_id as string;
          setSessionId(newSessionId);
          onSessionIdChange?.(newSessionId);
          saveLastSession(newSessionId, selectedProject?.id ?? null);
          if (selectedProject?.id) {
            window.history.replaceState({}, '', `/chat/${selectedProject.id}/${newSessionId}`);
          } else {
            window.history.replaceState({}, '', `/chat/${newSessionId}`);
          }
        }
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

  const handleExportExcel = async (aiIndex: number): Promise<void> => {
    const msg = messages[aiIndex];
    const exp = msg?.exportToExcel;
    if (!exp?.filename) return;
    try {
      if (exp.sessionFileId) {
        await downloadStoredSessionFile(exp.sessionFileId);
        return;
      }
      if (exp.base64) {
        triggerExcelDownload(exp);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to export';
      setMessages((prev) => [...prev, { text: `Error: ${message}`, isUser: false }]);
    }
  };

  const handleCancelSql = (aiIndex: number) => {
    const msg = messages[aiIndex];
    if (!msg || !msg.sqlToExecute) return;
    // Simply clear the sqlToExecute flag so the Execute button disappears.
    setMessages((prev) => {
      const updated = [...prev];
      updated[aiIndex] = { ...msg, sqlActionState: 'cancelled' };
      return updated;
    });
    const fallbackActionId =
      msg.sqlActionId || buildSqlActionId(
        sessionId,
        msg.text,
        msg.sqlToExecute,
        Math.max(0, messages.slice(0, aiIndex + 1).filter((m) => !!m.sqlToExecute).length - 1),
      );
    void executeSql(msg.sqlToExecute, fallbackActionId, sessionId, selectedProject?.id || null, 'en', true, 'cancelled');
  };

  // When switching to a *different* project: save current session for the project we're leaving, then clear UI.
  // This way when user comes back to that project, we restore the session instead of creating a new one (no duplicate history).
  const prevProjectIdRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    const currentId = selectedProject?.id;
    if (prevProjectIdRef.current !== undefined && prevProjectIdRef.current !== currentId) {
      saveLastSession(sessionId, prevProjectIdRef.current ?? null);
      setSessionId(null);
      setShareInfo(null);
      setMessages([]);
      setInputAttachedFiles([]);
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
          const sqlActionStates = getSqlActionStatesFromSessionResponse(res);
          let sqlOrdinal = 0;
          const convertedMessages: UiMessage[] = res.messages
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            .filter((msg: any) => msg.role === 'user' || msg.role === 'assistant')
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            .map((msg: any) => {
              const rawContent = msg.content || '';
              const cleanedText = stripInternalPayloads(rawContent);
              const schemaPreview =
                msg.role === 'assistant'
                  ? extractSchemaPreviewFromToolEvents((msg as any).tool_events) || extractSchemaPreview(rawContent)
                  : null;
              const sqlToExecute = msg.role === 'assistant' ? extractLastMutationSqlBlock(rawContent) : null;
              const markerActionId = msg.role === 'assistant' ? extractSqlActionId(rawContent) : undefined;
              const sqlActionId = sqlToExecute ? (markerActionId || buildSqlActionId(sid, cleanedText, sqlToExecute, sqlOrdinal++)) : undefined;
              const persistedSqlState = sqlActionId ? sqlActionStates[sqlActionId] : undefined;
              return {
                text: cleanedText,
                isUser: msg.role === 'user',
                attachments: msg.role === 'user' ? extractUploadAttachments(rawContent) : undefined,
                sqlToExecute,
                sqlActionId,
                sqlActionState: sqlToExecute ? (persistedSqlState ?? ('pending' as const)) : undefined,
                exportToExcel: msg.role === 'assistant' ? extractExportData(rawContent) : null,
                schemaPreview,
                schemaLocked: msg.role === 'assistant' ? !!schemaPreview : undefined,
              };
            })
            .filter((m) => m.text.trim().length > 0 || !!m.schemaPreview || !!m.sqlToExecute || !!m.exportToExcel || (m.attachments && m.attachments.length > 0));
          setMessages(convertedMessages);
          setInputAttachedFiles([]);
          setSessionId(sid);
          setShareInfo(res.share_info ?? null);
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

  const shareBanner = shareInfo ? (
    <div
      className={
        'px-4 py-2 text-sm border-b ' +
        (shareInfo.revoked
          ? 'bg-red-50 border-red-200 text-red-800'
          : shareInfo.permission === 'view_only'
            ? 'bg-amber-50 border-amber-200 text-amber-900'
            : shareInfo.permission === 'read_data'
              ? 'bg-blue-50 border-blue-200 text-blue-900'
              : 'bg-emerald-50 border-emerald-200 text-emerald-900')
      }
    >
      {shareInfo.revoked
        ? 'This shared chat has been revoked by the owner. You can no longer continue it.'
        : shareInfo.permission === 'view_only'
          ? 'This chat was shared with you in view-only mode — you cannot send messages.'
          : shareInfo.permission === 'read_data'
            ? 'This chat was shared with you in read-data mode — only SELECT queries are allowed.'
            : 'This chat was shared with you with full access to read and modify data.'}
    </div>
  ) : null;

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900">
      {shareBanner}
      {/* Chat Content */}
      {messages.length > 0 && (
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="max-w-5xl mx-auto w-full">
            <MessageList
              messages={messages}
              onRefreshResponse={(idx) => void handleRefreshResponse(idx)}
              onExecuteSql={(idx) => void handleExecuteSql(idx)}
              onCancelSql={(idx) => void handleCancelSql(idx)}
              onExportFile={(idx) => void handleExportExcel(idx)}
              onSchemaTypeChange={handleSchemaTypeChange}
              onToggleSchemaOptions={handleToggleSchemaOptions}
              onSchemaOptionChange={handleSchemaOptionChange}
              onConfirmSchema={(idx) => void handleConfirmSchema(idx)}
              onAssistantTypingChange={setIsAssistantTyping}
              typingStopSignal={typingStopSignal}
            />
            {streamingStage && (
              <div className="flex items-center gap-2 px-4 py-2 mt-2 text-sm text-gray-600">
                <span className="inline-block w-2 h-2 bg-indigo-500 rounded-full animate-pulse" />
                <span>{streamingStage}</span>
              </div>
            )}
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
              <h2 className="text-5xl md:text-6xl font-bold text-gray-900 dark:text-gray-100">Hi, How are you today?</h2>
            </div>
          )}
          <div className="relative bg-white dark:bg-slate-800 border-2 border-gray-300 dark:border-slate-700 rounded-3xl px-4 shadow-lg dark:shadow-none">
            <div className="flex flex-col">
              {(inputAttachedFiles.length > 0 || isUploadingExcel) && (
                <div className="flex flex-wrap items-center gap-2 pt-3 pb-3">
                  {isUploadingExcel && (
                    <span className="text-sm text-gray-500 dark:text-slate-400">File is loading…</span>
                  )}
                  {inputAttachedFiles.map((f) => (
                    <span
                      key={f.id}
                      className="inline-flex items-center gap-2 bg-gray-100 dark:bg-slate-700 text-gray-800 dark:text-slate-100 px-3 py-2.5 rounded-xl border border-gray-200 dark:border-slate-600 max-w-full min-w-0"
                    >
                      <img src={fileIcon} alt="" className="w-4 h-4 flex-shrink-0" />
                      <span className="text-sm sm:text-base font-semibold leading-snug truncate min-w-0 max-w-md">
                        {f.filename}
                      </span>
                      <button
                        type="button"
                        disabled={isViewOnlyShare}
                        className="shrink-0 text-base leading-none text-gray-500 hover:text-gray-800 dark:text-slate-400 dark:hover:text-slate-100 px-0.5 disabled:opacity-40 disabled:pointer-events-none"
                        aria-label={`Remove ${f.filename}`}
                        onClick={() => void handleRemoveInputAttachment(f.id)}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}

              <div
                className={`flex items-center gap-3 min-h-[48px] ${
                  inputAttachedFiles.length > 0 || isUploadingExcel
                    ? '-mx-4 px-4 border-t border-gray-300 dark:border-slate-600 pt-3'
                    : ''
                }`}
              >
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
                    accept=".xlsx,.xls,.csv,.pdf,.db,.sqlite,.txt,.md,application/pdf,application/x-sqlite3,text/csv,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
                    onChange={handleFileInputChange}
                  />
                </div>

                <textarea
                  key={inputKey}
                  ref={textareaRef}
                  value={query}
                  disabled={isViewOnlyShare}
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                    setQuery(e.target.value)
                  }
                  onKeyDown={(e: React.KeyboardEvent<HTMLTextAreaElement>) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      if (isStopVisible) return;
                      void handleSend();
                    }
                  }}
                  placeholder={
                    isViewOnlyShare
                      ? "Read-only shared chat — sending disabled"
                      : selectedProject
                        ? `New chat in ${selectedProject.name}`
                        : "Ask anything"
                  }
                  rows={1}
                  autoComplete="off"
                  autoCorrect="off"
                  spellCheck={false}
                  className="flex-1 resize-none outline-none text-lg bg-transparent text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500"
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
                    onClick={(): void => { if (isStopVisible) { handleStopResponse(); return; } void handleSend(); }}
                    disabled={!isStopVisible && !canSend}
                    className="flex items-center justify-center w-10 h-10 rounded-full p-0 opacity-60 hover:opacity-100 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
                    aria-label={isStopVisible ? "Stop" : "Send"}
                  >
                    <img src={isStopVisible ? stopCircleIcon : arrowUpCircleIcon} alt="" className="w-20 h-20" />
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
              <p className="text-center text-xs text-gray-500 dark:text-gray-400">
              By using LightDBee, you agree to our Term and Service Policy
              </p>
            </div>
          </div>
        )
      }

    </div >
  );
}

