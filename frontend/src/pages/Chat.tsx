import React, { useEffect, useMemo, useRef, useState } from 'react';
import MessageList, { type UiMessage, type SchemaPreviewData } from '../components/chat/MessageList';
import DataSourceBar, { buildDataSources, getActiveFileIds, type DataSource } from '../components/chat/DataSourceBar';
import AttachMenu from '../components/chat/AttachMenu';
import {
  getSession,
  sendMessageWithStream,
  getSessions,
  executeSql,
  resumeWorkflow,
  createSession,
  listUserFilesInventory,
  listSessionFiles,
  uploadSessionFile,
  deleteSessionFile,
  downloadStoredSessionFile,
  type SessionInfo,
  type SessionShareInfo,
  type SessionFileMeta,
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
import { Icons, BeeBadge } from '../icons';

const MAX_TEXTAREA_HEIGHT = 200;
const MIN_TEXTAREA_HEIGHT = 60;

const STORAGE_LAST_SESSION_ID = 'lastSessionId';
const STORAGE_LAST_SESSION_PROJECT = 'lastSessionIdForProject';


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
  const [selectedProject, setSelectedProject] = useState<{ id: string; name: string; description?: string } | null>(null);
  const [projectSessions, setProjectSessions] = useState<SessionInfo[]>([]);
  const [sessionPreviews, setSessionPreviews] = useState<Record<string, string>>({});
  const [inputKey, setInputKey] = useState(0);
  const previousProjectIdRef = useRef<string | null>(null);
  const hasRestoredSessionRef = useRef(false);
  const previousPropSessionIdRef = useRef<string | null | undefined>(undefined);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [isUploadingExcel, setIsUploadingExcel] = useState(false);
  /** Session files already uploaded to server (have a server ID). */
  const [inputAttachedFiles, setInputAttachedFiles] = useState<{ id: string; filename: string }[]>([]);
  /** Files selected locally but not yet uploaded — staged until Enter is pressed. */
  const [stagedFiles, setStagedFiles] = useState<{ localId: string; file: File; filename: string }[]>([]);
  /** Whether to show the "Save data / Q&A only" question above the input. */
  const [pendingStorageChoice, setPendingStorageChoice] = useState(false);
  /** Message payload waiting to be sent after storage choice is made. */
  const pendingSendPayloadRef = useRef<string | null>(null);
  const [isAssistantTyping, setIsAssistantTyping] = useState(false);
  const [typingStopSignal, setTypingStopSignal] = useState(0);
  // Live progress label streamed from the backend (e.g. "Đang sinh SQL...").
  // Null when no streaming chat is in flight.
  const [streamingStage, setStreamingStage] = useState<string | null>(null);
  const sendAbortControllerRef = useRef<AbortController | null>(null);

  // Data source selector (multi-select: DB is exclusive with files, multiple files allowed)
  const [sessionFiles, setSessionFiles] = useState<SessionFileMeta[]>([]);
  const [activeDataSources, setActiveDataSources] = useState<DataSource[]>([]);

  const handleToggleDataSource = (src: DataSource) => {
    setActiveDataSources((prev) => {
      const isAlreadySelected =
        src.type === 'primary_db'
          ? prev.some((s) => s.type === 'primary_db')
          : prev.some((s) => s.type === 'file' && s.id === src.id);

      if (isAlreadySelected) {
        if (src.type === 'primary_db') return prev.filter((s) => s.type !== 'primary_db');
        return prev.filter((s) => !(s.type === 'file' && s.id === src.id));
      }

      return [...prev, src];
    });
  };

  // Read connected DB label from localStorage (written by Sidebar)
  const connectedDbLabel = (() => {
    try {
      const raw = localStorage.getItem('connectedDb');
      if (!raw) return null;
      const parsed = JSON.parse(raw) as { server?: string; databaseName?: string };
      if (parsed?.databaseName) return `${parsed.databaseName}@${parsed.server ?? 'localhost'}`;
    } catch { /* ignore */ }
    return null;
  })();

  // Load selected project from URL (propProjectId) - URL is source of truth
  useEffect(() => {
    if (propProjectId) {
      // Load project from URL
      const projects = JSON.parse(localStorage.getItem('projects') || '[]');
      const project = projects.find((p: { id: string }) => p.id === propProjectId);
      if (project) {
        setSelectedProject({ id: project.id, name: project.name, description: project.description });
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

  const getSqlActionStatesFromSessionResponse = (res: GetSessionResponse): Record<string, 'pending' | 'running' | 'executed' | 'failed' | 'cancelled'> => {
    if (!res.success) return {};
    const raw = (res.session_info as any)?.sql_action_states;
    if (!raw || typeof raw !== 'object') return {};
    const out: Record<string, 'pending' | 'running' | 'executed' | 'failed' | 'cancelled'> = {};
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      const value = String(v || '').toLowerCase();
      if (value === 'pending' || value === 'running' || value === 'executed' || value === 'failed' || value === 'cancelled') {
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
    const hasText = query.trim().length > 0;
    if (isViewOnlyShare) return false;
    return !isStopVisible && !isUploadingExcel && !pendingStorageChoice && hasText;
  }, [isStopVisible, isUploadingExcel, pendingStorageChoice, query, isViewOnlyShare]);

  const handleRemoveInputAttachment = async (fileId: string) => {
    // Staged files (not yet uploaded) — just remove locally
    if (fileId.startsWith('staged-')) {
      setStagedFiles((prev) => prev.filter((f) => f.localId !== fileId));
      return;
    }
    // Uploaded files — delete from server
    try {
      await deleteSessionFile(fileId);
      setInputAttachedFiles((prev) => prev.filter((f) => f.id !== fileId));
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Remove failed');
    }
  };

  /** Upload all staged files to server with the chosen storage destination. */
  const uploadStagedFiles = async (
    useProjectDb: boolean,
    filesToUpload?: { localId: string; file: File; filename: string }[],
  ): Promise<{ id: string; filename: string }[]> => {
    const toUpload = filesToUpload ?? [...stagedFiles];
    if (toUpload.length === 0) return [];
    setIsUploadingExcel(true);
    const uploaded: { id: string; filename: string }[] = [];
    try {
      let sid = sessionId;
      if (!sid) {
        const cr = await createSession(null, selectedProject?.id || propProjectId || null);
        if (!cr.success || !cr.session_id) {
          window.alert('Could not create a chat session for this upload');
          return [];
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
      for (const staged of toUpload) {
        try {
          const { file: up } = await uploadSessionFile(
            sid!,
            staged.file,
            selectedProject?.id || propProjectId || null,
            useProjectDb,
          );
          uploaded.push({ id: up.id, filename: up.filename });
        } catch (err) {
          const e = err as Error & { code?: string };
          if (e.code === 'storage_quota_exceeded' || /5\s*GB|storage limit/i.test(e.message || '')) {
            try {
              const inv = await listUserFilesInventory();
              const lines = inv.slice(0, 12).map(
                (r) => `• ${r.filename} (${(r.size_bytes / (1024 * 1024)).toFixed(1)} MB) — session ${r.session_id.slice(0, 8)}…`,
              );
              window.alert(
                'Storage limit reached (5 GB). Delete some files and try again.\n\n' +
                  (lines.length ? `Recent files:\n${lines.join('\n')}` : ''),
              );
            } catch {
              window.alert('Storage limit reached (5 GB). Delete some files and try again.');
            }
          } else {
            window.alert(e instanceof Error ? e.message : 'Failed to upload file');
          }
        }
      }
      setStagedFiles([]);
      setInputAttachedFiles((prev) => [...prev, ...uploaded]);
      // Refresh session files list for DataSource selector
      if (sessionId && uploaded.length > 0) {
        listSessionFiles(sessionId).then(setSessionFiles).catch(() => {});
      }
      return uploaded;
    } finally {
      setIsUploadingExcel(false);
    }
  };

  /** Stage file locally — actual upload happens on Enter. */
  const handleExcelFileSelected = (file: File) => {
    const localId = `staged-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setStagedFiles((prev) => [...prev, { localId, file, filename: file.name }]);
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

  // Fetch session files for the DataSource selector whenever session changes
  useEffect(() => {
    if (!sessionId) {
      setSessionFiles([]);
      setActiveDataSources([]);
      return;
    }
    listSessionFiles(sessionId)
      .then((files) => {
        setSessionFiles(files);
        // Auto-select only when user hasn't made a choice yet
        setActiveDataSources((prev) => {
          if (prev.length > 0) return prev;
          const hasPrimaryDb = !!connectedDbLabel;
          // Only DB and no files → auto-select DB
          if (hasPrimaryDb && files.length === 0) {
            return [{ type: 'primary_db', label: 'Database', detail: connectedDbLabel! }];
          }
          // Only 1 file and no DB → auto-select that file
          if (!hasPrimaryDb && files.length === 1) {
            const f = files[0];
            return [{ type: 'file', id: f.id, filename: f.filename, mime_type: f.mime_type, uploaded_at: f.uploaded_at ?? null }];
          }
          return [];
        });
      })
      .catch(() => setSessionFiles([]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

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
    setStreamingStage('Processing');
    const controller = new AbortController();
    sendAbortControllerRef.current = controller;
    console.log('Sending message with sessionId:', sessionId);
    console.log('Selected project:', selectedProject);
    try {
      const finalRes = await sendMessageWithStream(text, sessionId, selectedProject?.id || null, {
        onStage: (m) => setStreamingStage(m),
        signal: controller.signal,
        activeFileIds: getActiveFileIds(activeDataSources),
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
    const activeProjectId = selectedProject?.id || propProjectId;

    // Ask "save data vs Q&A only" when there are staged files AND there's a
    // place to import into: inside a project always, or in a regular chat only
    // while a database is connected. With no project and no DB connection there's
    // nowhere to save, so skip the question and just do Q&A.
    if (stagedFiles.length > 0 && (activeProjectId || connectedDbLabel)) {
      const attachmentsForUi = [
        ...inputAttachedFiles.map((f) => ({ name: f.filename, fileId: f.id })),
        ...stagedFiles.map((f) => ({ name: f.filename })),
      ];
      lockAllSchemaPreviews();
      setMessages((prev) => [
        ...prev,
        {
          text: displayText,
          isUser: true,
          ...(attachmentsForUi.length > 0 ? { attachments: attachmentsForUi } : {}),
        },
      ]);
      setQuery('');
      setInputKey((k) => k + 1);
      pendingSendPayloadRef.current = displayText;
      setPendingStorageChoice(true);
      return;
    }

    // Show message in chat immediately, then upload and send
    const attachmentsForUi = [
      ...inputAttachedFiles.map((f) => ({ name: f.filename, fileId: f.id })),
      ...stagedFiles.map((f) => ({ name: f.filename })),
    ];
    lockAllSchemaPreviews();
    setMessages((prev) => [
      ...prev,
      {
        text: displayText,
        isUser: true,
        ...(attachmentsForUi.length > 0 ? { attachments: attachmentsForUi } : {}),
      },
    ]);
    setQuery('');
    setInputKey((k) => k + 1);

    // Capture and clear staged files immediately
    const captured = [...stagedFiles];
    setStagedFiles([]);
    const prevUploaded = [...inputAttachedFiles];
    setInputAttachedFiles([]);

    // Upload staged files (if any) then send
    const newUploaded = captured.length > 0 ? await uploadStagedFiles(false, captured) : [];
    setInputAttachedFiles([]); // uploadStagedFiles adds to inputAttachedFiles internally — clear again
    const allAttached = [...prevUploaded, ...newUploaded];
    const sendPayload = buildChatMessageWithSessionFiles(displayText, allAttached);
    await doSend(sendPayload);
  };

  /** Called after user picks storage destination — upload staged files then send. */
  const handleStorageChoice = async (useProjectDb: boolean) => {
    // Capture and clear staged files immediately so chips don't flash back
    const captured = [...stagedFiles];
    setStagedFiles([]);
    setPendingStorageChoice(false);
    const displayText = pendingSendPayloadRef.current ?? '';
    pendingSendPayloadRef.current = null;

    const prevUploaded = [...inputAttachedFiles];
    const newUploaded = await uploadStagedFiles(useProjectDb, captured);
    setInputAttachedFiles([]); // uploadStagedFiles adds internally — clear again
    const allAttached = [...prevUploaded, ...newUploaded];

    const sendPayload = buildChatMessageWithSessionFiles(displayText, allAttached);
    await doSend(sendPayload);
  };

  /** Start a fresh chat inside the current project (from the project view). */
  const handleNewChatInProject = async () => {
    const pid = selectedProject?.id || propProjectId;
    if (!pid) return;
    try {
      const cr = await createSession(null, pid);
      if (cr.success && cr.session_id) {
        saveLastSession(cr.session_id, pid);
        window.history.pushState({}, '', `/chat/${pid}/${cr.session_id}`);
        window.dispatchEvent(new PopStateEvent('popstate'));
        onSessionIdChange?.(cr.session_id);
      } else {
        window.alert('Failed to create new chat');
      }
    } catch {
      window.alert('Failed to create new chat');
    }
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
      const res = await sendMessageWithStream(sendPayload, sessionId, selectedProject?.id || null, { activeFileIds: getActiveFileIds(activeDataSources) });
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

    // Show a loading state while the query runs (reference SqlPreview "running").
    setMessages((prev) => {
      const updated = [...prev];
      const current = updated[aiIndex];
      if (current) {
        updated[aiIndex] = { ...current, sqlActionState: 'running' };
      }
      return updated;
    });

    setIsLoading(true);
    try {
      const fallbackActionId =
        msg.sqlActionId || buildSqlActionId(
          sessionId,
          msg.text,
          msg.sqlToExecute,
          Math.max(0, messages.slice(0, aiIndex + 1).filter((m) => !!m.sqlToExecute).length - 1),
        );
      const res = await executeSql(msg.sqlToExecute, fallbackActionId, sessionId, selectedProject?.id || null, false, null);
      if (res.success) {
        const resText = res.response ?? '';
        const cleanedRaw = stripInternalPayloads(resText);
        // A bare "Successfully executed the SQL." carries no info beyond the
        // success itself — the green "Executed" chip already says that, so
        // don't append it as a separate text bubble. Keep any real follow-up
        // (a result table, another SQL preview, affected-rows detail, …).
        const isPlainSuccess =
          !/```|(\n\s*\|.*\|)/.test(cleanedRaw) &&
          /successfully executed/i.test(cleanedRaw) &&
          cleanedRaw.trim().length < 80;
        setMessages((prev) => {
          const updated = [...prev];
          const current = updated[aiIndex];
          if (current) {
            // Mark executed → action row shows the success chip.
            updated[aiIndex] = { ...current, sqlActionState: 'executed' };
          }
          if (isPlainSuccess) return updated;
          return [
            ...updated,
            {
              text: buildAssistantTextFromSqlPreview(
                cleanedRaw,
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
        // Mark failed (red "Query failed" card) — the Execute button stays so
        // the user can retry.
        setMessages((prev) => {
          const updated = [...prev];
          const current = updated[aiIndex];
          if (current) updated[aiIndex] = { ...current, sqlActionState: 'failed' };
          return [...updated, { text: `Error: ${res.error || 'Failed to execute SQL'}`, isUser: false }];
        });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to execute SQL';
      setMessages((prev) => {
        const updated = [...prev];
        const current = updated[aiIndex];
        if (current) updated[aiIndex] = { ...current, sqlActionState: 'failed' };
        return [...updated, { text: `Error: ${message}`, isUser: false }];
      });
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
    void executeSql(msg.sqlToExecute, fallbackActionId, sessionId, selectedProject?.id || null, true, 'cancelled');
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
      style={{
        padding: '10px 24px', fontSize: 13.5, borderBottom: '1px solid var(--border)',
        background: shareInfo.revoked
          ? 'oklch(0.95 0.05 25)'
          : shareInfo.permission === 'view_only'
            ? 'var(--accent-soft)'
            : 'var(--info-soft)',
        color: shareInfo.revoked ? 'oklch(0.5 0.18 25)' : 'var(--text)',
      }}
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

  const greetHour = new Date().getHours();
  const greeting = greetHour < 12 ? 'Good morning' : greetHour < 18 ? 'Good afternoon' : 'Good evening';
  const hasFiles = inputAttachedFiles.length > 0 || stagedFiles.length > 0;

  const composer = (
    <div className="card soft-shadow" style={{ borderRadius: 'var(--r-lg)', padding: '14px 16px 12px', maxWidth: 760, margin: '0 auto', width: '100%' }}>
      <input
        ref={fileInputRef}
        type="file"
        style={{ display: 'none' }}
        multiple={false}
        accept=".xlsx,.xls,.csv,.pdf,.db,.sqlite,.txt,.md,application/pdf,application/x-sqlite3,text/csv,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
        onChange={handleFileInputChange}
      />

      {/* Staged / attached files */}
      {!pendingStorageChoice && hasFiles && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
          {inputAttachedFiles.map((f) => (
            <div key={f.id} className="scale-in" style={{ display: 'inline-flex', alignItems: 'center', gap: 9, padding: '7px 9px 7px 8px', borderRadius: 'var(--r-sm)', border: '1px solid var(--border)', background: 'var(--surface-2)' }}>
              <span style={{ width: 28, height: 28, borderRadius: 7, display: 'grid', placeItems: 'center', background: 'var(--green-soft)', color: 'var(--green-ink)', flexShrink: 0 }}>
                <Icons.File size={15} />
              </span>
              <span style={{ fontSize: 13, fontWeight: 600, maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.filename}</span>
              <button
                type="button"
                disabled={isViewOnlyShare || isUploadingExcel}
                onClick={() => void handleRemoveInputAttachment(f.id)}
                className="focusable"
                aria-label={`Remove ${f.filename}`}
                style={{ width: 22, height: 22, borderRadius: 6, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', background: 'transparent', border: 'none', flexShrink: 0 }}
              >
                <Icons.Close size={14} />
              </button>
            </div>
          ))}
          {stagedFiles.map((f) => (
            <div key={f.localId} className="scale-in" style={{ display: 'inline-flex', alignItems: 'center', gap: 9, padding: '7px 9px 7px 8px', borderRadius: 'var(--r-sm)', border: '1px dashed var(--border-strong)', background: 'var(--surface-2)' }}>
              <span style={{ width: 28, height: 28, borderRadius: 7, display: 'grid', placeItems: 'center', background: 'var(--green-soft)', color: 'var(--green-ink)', flexShrink: 0, opacity: 0.7 }}>
                <Icons.File size={15} />
              </span>
              <span style={{ fontSize: 13, fontWeight: 600, maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.filename}</span>
              <button
                type="button"
                disabled={isViewOnlyShare || pendingStorageChoice || isUploadingExcel}
                onClick={() => void handleRemoveInputAttachment(f.localId)}
                className="focusable"
                aria-label={`Remove ${f.filename}`}
                style={{ width: 22, height: 22, borderRadius: 6, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', background: 'transparent', border: 'none', flexShrink: 0 }}
              >
                <Icons.Close size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      <textarea
        key={inputKey}
        ref={textareaRef}
        value={query}
        disabled={isViewOnlyShare}
        onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setQuery(e.target.value)}
        onKeyDown={(e: React.KeyboardEvent<HTMLTextAreaElement>) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (isStopVisible) return;
            void handleSend();
          }
        }}
        placeholder={
          isViewOnlyShare
            ? 'Read-only shared chat — sending disabled'
            : selectedProject
              ? `New chat in ${selectedProject.name}`
              : 'Ask anything about your data…'
        }
        rows={1}
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        style={{
          width: '100%', border: 'none', outline: 'none', background: 'transparent',
          fontSize: 16, lineHeight: 1.5, color: 'var(--text)', resize: 'none',
          maxHeight: `${MAX_TEXTAREA_HEIGHT}px`, minHeight: `${MIN_TEXTAREA_HEIGHT}px`,
          paddingTop: 8, paddingBottom: 4,
        }}
      />

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 8, gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          <AttachMenu
            onUploadDevice={() => fileInputRef.current?.click()}
            disabled={isViewOnlyShare || isUploadingExcel}
          />
          {/* Data source selector */}
          {(() => {
            const sources = buildDataSources(sessionFiles, connectedDbLabel);
            return sources.length > 1 ? (
              <div style={{ marginBottom: -12 }}>
                <DataSourceBar sources={sources} active={activeDataSources} onToggle={handleToggleDataSource} />
              </div>
            ) : null;
          })()}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          <button
            type="button"
            title="Voice input"
            className="focusable"
            style={{ width: 36, height: 36, borderRadius: 10, display: 'grid', placeItems: 'center', color: 'var(--text-soft)', background: 'transparent', border: 'none' }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <Icons.Mic size={19} />
          </button>
          <button
            type="button"
            onClick={(): void => { if (isStopVisible) { handleStopResponse(); return; } void handleSend(); }}
            disabled={!isStopVisible && !canSend}
            title={isStopVisible ? 'Stop' : 'Send'}
            className="focusable"
            style={{
              width: 40, height: 40, borderRadius: 12, display: 'grid', placeItems: 'center', transition: 'all .15s', border: 'none',
              background: (isStopVisible || canSend) ? 'var(--accent)' : 'var(--surface-3)',
              color: (isStopVisible || canSend) ? 'var(--on-accent)' : 'var(--text-faint)',
              cursor: (isStopVisible || canSend) ? 'pointer' : 'default',
              boxShadow: (isStopVisible || canSend) ? '0 4px 12px -4px hsl(var(--shadow-color)/.5)' : 'none',
            }}
            aria-label={isStopVisible ? 'Stop' : 'Send'}
          >
            {isStopVisible ? <Icons.Stop size={20} /> : <Icons.ArrowUp size={20} />}
          </button>
        </div>
      </div>
    </div>
  );

  const storageChoice = pendingStorageChoice ? (
    <div className="card scale-in" style={{ maxWidth: 760, margin: '0 auto 12px', borderRadius: 'var(--r)', overflow: 'hidden', borderColor: 'var(--accent-soft-2)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '13px 16px', borderBottom: '1px solid var(--border)', background: 'var(--accent-soft)' }}>
        <span style={{ color: 'var(--accent-ink)', flexShrink: 0 }}><Icons.Question size={18} /></span>
        <span style={{ fontSize: 14.5, fontWeight: 700, color: 'var(--text)' }}>Do you want to save this file's data, or just ask questions about it?</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12 }}>
        {[
          { save: false, icon: <Icons.Question size={17} />, bg: 'var(--surface-3)', color: 'var(--text-soft)', title: 'Q&A only', desc: "Ask about this file now — don't store it in the database." },
          { save: true, icon: <Icons.Database size={17} />, bg: 'var(--green-soft)', color: 'var(--green-ink)', title: 'Save data', desc: "Store this file's data so you can query it anytime." },
        ].map((opt) => (
          <button
            key={String(opt.save)}
            type="button"
            onClick={() => void handleStorageChoice(opt.save)}
            className="focusable"
            style={{ display: 'flex', alignItems: 'flex-start', gap: 12, textAlign: 'left', padding: '12px 14px', borderRadius: 'var(--r-sm)', border: '1px solid var(--border)', background: 'var(--surface)', transition: 'all .13s' }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.background = 'var(--accent-soft)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.background = 'var(--surface)'; }}
          >
            <span style={{ width: 32, height: 32, borderRadius: 9, flexShrink: 0, display: 'grid', placeItems: 'center', background: opt.bg, color: opt.color }}>{opt.icon}</span>
            <span>
              <span style={{ display: 'block', fontSize: 14, fontWeight: 700 }}>{opt.title}</span>
              <span style={{ display: 'block', fontSize: 12.5, color: 'var(--text-muted)', marginTop: 1 }}>{opt.desc}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  ) : null;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, background: 'var(--bg)' }}>
      {shareBanner}

      {/* Conversation */}
      {messages.length > 0 && (
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <div style={{ maxWidth: 760, margin: '0 auto', padding: '32px 24px 24px' }}>
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
              <div className="fade-in" style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 0', marginTop: 14 }}>
                <BeeBadge size={30} />
                <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                  <span style={{ fontSize: 14.5, color: 'var(--text-soft)', fontWeight: 500 }}>{streamingStage}</span>
                  <span style={{ display: 'inline-flex', gap: 4 }}>
                    {[0, 1, 2].map((i) => (
                      <span key={i} style={{ width: 6, height: 6, borderRadius: 99, background: 'var(--accent-strong)', animation: `dotPulse 1.2s ${i * 0.18}s infinite ease-in-out` }} />
                    ))}
                  </span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      {/* Empty state: greeting + composer grouped and centered */}
      {isEmptyState ? (
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '40px 24px' }}>
          <div style={{ width: '100%', maxWidth: 760, margin: '0 auto' }}>
            <div className="fade-up" style={{ marginBottom: 18 }}>
              <BeeBadge size={56} />
            </div>
            <h1 className="fade-up" style={{ fontSize: 38, fontWeight: 800, letterSpacing: '-.025em', lineHeight: 1.1 }}>{greeting}.</h1>
            <p className="fade-up" style={{ fontSize: 19, color: 'var(--text-soft)', marginTop: 8, marginBottom: 26, animationDelay: '.09s' }}>
              Ask a question about your data in plain English — I'll find the answer, show it as a table or chart, and explain it.
            </p>
            {storageChoice}
            {composer}
            <p style={{ textAlign: 'center', fontSize: 12, color: 'var(--text-faint)', marginTop: 11 }}>
              LightDBee can make mistakes. It always asks before changing your data.
            </p>
          </div>
        </div>
      ) : projectHasHistory ? null : (
        /* Active conversation: composer pinned below. (Project landing view
           has its own "New chat in this project" CTA, so no composer here.) */
        <div style={{ padding: '12px 24px 22px', background: 'var(--bg)' }}>
          {storageChoice}
          {composer}
          {messages.length > 0 && (
            <p style={{ textAlign: 'center', fontSize: 12, color: 'var(--text-faint)', marginTop: 11 }}>
              LightDBee can make mistakes. It always asks before changing your data.
            </p>
          )}
        </div>
      )}

      {/* Project chat history */}
      {projectHasHistory && (
        <div style={{ flex: 1, overflowY: 'auto', padding: '44px 24px 40px' }}>
          <div style={{ maxWidth: 760, margin: '0 auto' }}>
            {/* Project header */}
            <div className="fade-up" style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
              <div style={{ width: 52, height: 52, borderRadius: 15, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}>
                <Icons.Folder size={26} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <h1 style={{ fontSize: 30, fontWeight: 800, letterSpacing: '-.02em', lineHeight: 1.15 }}>{selectedProject?.name}</h1>
                {selectedProject?.description && (
                  <p style={{ fontSize: 15.5, color: 'var(--text-soft)', marginTop: 6, lineHeight: 1.5 }}>{selectedProject.description}</p>
                )}
              </div>
            </div>

            <div className="fade-up" style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 22, animationDelay: '.05s' }}>
              <button type="button" onClick={() => void handleNewChatInProject()} className="btn btn-primary" style={{ padding: '11px 18px' }}>
                <Icons.NewChat size={16} />
                New chat in this project
              </button>
            </div>

            <div style={{ fontSize: 12.5, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--text-faint)', margin: '34px 0 12px' }}>
              {projectSessions.length} chats
            </div>
            <div className="card" style={{ overflow: 'hidden' }}>
              {projectSessions.map((session, index) => (
                <button
                  key={session.session_id}
                  onClick={() => {
                    if (selectedProject) {
                      window.history.pushState({}, '', `/chat/${selectedProject.id}/${session.session_id}`);
                    } else {
                      window.history.pushState({}, '', `/chat/${session.session_id}`);
                    }
                    window.dispatchEvent(new PopStateEvent('popstate'));
                    if (onSessionIdChange) onSessionIdChange(session.session_id);
                  }}
                  type="button"
                  className="focusable"
                  style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 13, padding: '14px 18px', textAlign: 'left', borderTop: index ? '1px solid var(--border)' : 'none', background: 'transparent', border: 'none', borderTopWidth: index ? 1 : 0 }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                >
                  <span style={{ width: 34, height: 34, borderRadius: 9, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
                    <Icons.NewChat size={16} />
                  </span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: 'block', fontSize: 14.5, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{formatSessionName(session)}</span>
                    {sessionPreviews[session.session_id] && (
                      <span style={{ display: 'block', fontSize: 12.5, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sessionPreviews[session.session_id]}</span>
                    )}
                  </span>
                  {session.created_at && (
                    <span style={{ fontSize: 12, color: 'var(--text-faint)', flexShrink: 0 }}>{formatDate(session.created_at)}</span>
                  )}
                  <Icons.ChevronRight size={17} style={{ color: 'var(--text-faint)', flexShrink: 0 }} />
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

