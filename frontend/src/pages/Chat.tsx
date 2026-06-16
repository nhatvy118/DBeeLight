import React, { useEffect, useMemo, useRef, useState } from 'react';
import MessageList, { type UiMessage } from '../components/chat/MessageList';
import DataSourceBar, { buildDataSources, getActiveFileIds, type DataSource } from '../components/chat/DataSourceBar';
import AttachMenu from '../components/chat/AttachMenu';
import { toast } from '../components/Toaster';
import { confirm } from '../components/ConfirmDialog';
import {
  getSession,
  getMessages,
  sendMessageWithStream,
  getSessions,
  deleteChatSession,
  executeSql,
  resumeWorkflow,
  createSession,
  listUserFilesInventory,
  listSessionFiles,
  uploadSessionFile,
  downloadStoredSessionFile,
  saveChart,
  type SessionInfo,
  type SessionShareInfo,
  type SessionFileMeta,
  type ImportMode,
  type ToolEvent,
  type GetSessionResponse,
  type SessionMessage,
  type ChartRecipe,
} from '../services/api';
import {
  readSqlPreview,
  isSqlExecuted,
  readSchemaPreview,
  readFileExport,
  readSessionFiles,
  readCharts,
  triggerExcelDownload,
  type SqlPreviewData,
} from '../utils/toolEvents';
import { Icons, BeeBadge } from '../icons';
import { FileTypeBadge } from '../utils/fileType';

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
  const [isSending, setIsSending] = useState<boolean>(false);
  const [isSessionLoading, setIsSessionLoading] = useState<boolean>(false);
  // Don't init from propSessionId: so on reload with URL like /chat/projectId/sessionId,
  // the "load session" effect sees propSessionId set but sessionId null and fetches messages.
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [shareInfo, setShareInfo] = useState<SessionShareInfo | null>(null);
  const [selectedProject, setSelectedProject] = useState<{ id: string; name: string; description?: string } | null>(null);
  const [projectSessions, setProjectSessions] = useState<SessionInfo[]>([]);
  const [inputKey, setInputKey] = useState(0);
  const previousProjectIdRef = useRef<string | null>(null);
  const hasRestoredSessionRef = useRef(false);
  const previousPropSessionIdRef = useRef<string | null | undefined>(undefined);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [isUploadingFile, setIsUploadingFile] = useState(false);
  /** Files selected locally but not yet uploaded — staged until Enter is pressed. */
  const [stagedFiles, setStagedFiles] = useState<{ localId: string; file: File; filename: string }[]>([]);
  /** Progress while uploading staged files after Send (null when idle). */
  const [fileUploadProgress, setFileUploadProgress] = useState<{
    done: number;
    total: number;
    filename: string;
  } | null>(null);
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
  // Primary-DB info for the current session, from the backend (single source of truth:
  // project_id → project DB, else user's active external DB). null = not loaded yet.
  const [sessionDb, setSessionDb] = useState<
    { has_db: boolean; db_kind: 'project' | 'external' | null; db_label: string | null } | null
  >(null);

  // Scope ids for a chat turn: the picked files, or the primary-DB sentinel when none are
  // picked ("no file selected = ask the database"). The backend reads '__primary_db__'.
  const scopedFileIds = (fileIds: string[]): string[] => (fileIds.length ? fileIds : ['__primary_db__']);

  const handleToggleDataSource = (src: DataSource) => {
    setActiveDataSources((prev) => {
      const selected = prev.some((s) => s.id === src.id);
      return selected ? prev.filter((s) => s.id !== src.id) : [...prev, src];
    });
  };

  // Primary DB shown in the data-source selector. The backend is the source of truth
  // (sessionDb, from getSession): project DB vs external DB vs none. Before it loads we
  // briefly fall back to the selected project so a project chat shows its DB without a flash.
  const primaryDbLabel = sessionDb
    ? (sessionDb.has_db ? (sessionDb.db_label || 'Database') : null)
    : (selectedProject ? (selectedProject.name || 'Database') : null);

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
  // Cursor pagination for message history (scroll up to load older).
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const [oldestCursor, setOldestCursor] = useState<string | null>(null);
  const [hasMoreMessages, setHasMoreMessages] = useState(false);
  const isLoadingOlderRef = useRef(false);
  const skipAutoScrollRef = useRef(false);  // set when prepending older msgs, so we don't jump to bottom

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

  const isDqlStatement = (typeSql?: string) => (typeSql ?? '').trim().toUpperCase() === 'DQL';

  const pendingWorkflowResumeFromMessage = (msg: { pending_workflow_resume?: boolean }) =>
    Boolean(msg?.pending_workflow_resume);

  const resolveSqlExecuteAction = (
    events: ToolEvent[] | undefined,
    _pendingWorkflowResume: boolean,
  ): { sqlToExecute: string | null; sqlActionState: 'pending' | 'executed' | undefined } => {
    if (isSqlExecuted(events)) {
      return { sqlToExecute: null, sqlActionState: 'executed' };
    }
    const payload = readSqlPreview(events);
    if (!payload?.sql) {
      return { sqlToExecute: null, sqlActionState: undefined };
    }
    const typeSql = payload.type_sql?.trim() ?? '';
    if (!typeSql) {
      return { sqlToExecute: null, sqlActionState: undefined };
    }
    if (isDqlStatement(typeSql)) {
      return { sqlToExecute: null, sqlActionState: 'executed' };
    }
    // A DML/DDL preview that hasn't run yet → pending → show the Execute button. The
    // sql_preview event itself signals "awaiting approval" (it's persisted), so we don't
    // depend on the live-only pending_workflow_resume flag — survives a history reload.
    return { sqlToExecute: payload.sql, sqlActionState: 'pending' };
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

  const SCHEMA_CONFIRM_USER_RE = /^Confirm schema table /i;

  /** Locked only after the user explicitly confirmed schema in chat history. */
  const deriveSchemaLockedFromHistory = (
    rawMessages: SessionMessage[],
    assistantIndex: number,
  ): boolean => {
    for (let i = assistantIndex + 1; i < rawMessages.length; i += 1) {
      const m = rawMessages[i];
      if (m.role === 'user' && SCHEMA_CONFIRM_USER_RE.test((m.content || '').trim())) {
        return true;
      }
      if (m.role === 'assistant') {
        const text = m.content || '';
        if (/```\s*sql[\s\S]*CREATE\s+TABLE/i.test(text)) {
          return true;
        }
      }
    }
    return false;
  };

  const getDbInfoFromSessionResponse = (
    res: GetSessionResponse,
  ): { has_db: boolean; db_kind: 'project' | 'external' | null; db_label: string | null } | null => {
    if (!res.success) return null;
    const info = res.session_info as any;
    if (!info || typeof info.has_db !== 'boolean') return null;
    const kind = info.db_kind === 'project' || info.db_kind === 'external' ? info.db_kind : null;
    return { has_db: info.has_db, db_kind: kind, db_label: info.db_label ?? null };
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

  // Convert raw message rows (oldest→newest) into UI messages. Shared by initial load and scroll-up.
  const convertMessages = (
    raw: SessionMessage[],
    sid: string,
    sqlActionStates: Record<string, 'pending' | 'running' | 'executed' | 'failed' | 'cancelled'>,
  ): UiMessage[] => {
    let sqlOrdinal = 0;
    const filteredMessages = raw.filter((msg) => msg.role === 'user' || msg.role === 'assistant');
    return filteredMessages
      .map((msg, msgIndex) => {
        const cleanedText = (msg.content || '').trim();
        const sqlPreview =
          msg.role === 'assistant' ? readSqlPreview(msg.tool_events) : null;
        const schemaPreview =
          msg.role === 'assistant'
            ? readSchemaPreview(msg.tool_events)
            : null;
        const sqlAction =
          msg.role === 'assistant'
            ? resolveSqlExecuteAction(msg.tool_events, pendingWorkflowResumeFromMessage(msg))
            : { sqlToExecute: null, sqlActionState: undefined };
        const sqlToExecute = sqlAction.sqlToExecute;
        const sqlActionId = sqlToExecute ? buildSqlActionId(sid, cleanedText, sqlToExecute, sqlOrdinal++) : undefined;
        const persistedSqlState = sqlActionId ? sqlActionStates[sqlActionId] : undefined;
        return {
          text: msg.role === 'assistant' ? buildAssistantTextFromSqlPreview(cleanedText, sqlPreview) : cleanedText,
          isUser: msg.role === 'user',
          attachments: msg.role === 'user' ? readSessionFiles(msg.tool_events) : undefined,
          sqlToExecute,
          sqlActionId,
          sqlActionState: sqlToExecute
            ? (persistedSqlState ?? sqlAction.sqlActionState ?? ('pending' as const))
            : sqlAction.sqlActionState,
          exportToExcel: msg.role === 'assistant' ? readFileExport(msg.tool_events) : null,
          charts: msg.role === 'assistant' ? readCharts(msg.tool_events) : undefined,
          schemaPreview,
          schemaLocked:
            msg.role === 'assistant' && schemaPreview
              ? deriveSchemaLockedFromHistory(filteredMessages, msgIndex)
              : undefined,
        };
      })
      .filter((m) => m.text.trim().length > 0 || !!m.schemaPreview || !!m.sqlToExecute || !!m.exportToExcel || (m.charts && m.charts.length > 0) || (m.attachments && m.attachments.length > 0));
  };

  // Load the previous (older) page when the user scrolls to the top of the conversation.
  const loadOlderMessages = async () => {
    if (!sessionId || !oldestCursor || isLoadingOlderRef.current || !hasMoreMessages) return;
    isLoadingOlderRef.current = true;
    const el = scrollContainerRef.current;
    const prevHeight = el?.scrollHeight ?? 0;
    try {
      const page = await getMessages(sessionId, oldestCursor);
      // sql_action_states only ride on session_info (initial load); older pages have none.
      const older = convertMessages(page.messages, sessionId, {});
      if (older.length) {
        skipAutoScrollRef.current = true;  // prepend must not yank the view to the bottom
        setMessages((prev) => [...older, ...prev]);
        // Keep the viewport anchored on the same message after the taller list renders.
        requestAnimationFrame(() => {
          const el2 = scrollContainerRef.current;
          if (el2) el2.scrollTop = el2.scrollHeight - prevHeight;
        });
      }
      setOldestCursor(page.next_cursor);
      setHasMoreMessages(page.has_more);
    } catch (err) {
      console.error('Failed to load older messages:', err);
    } finally {
      isLoadingOlderRef.current = false;
    }
  };

  const handleMessagesScroll = (e: React.UIEvent<HTMLDivElement>) => {
    if (e.currentTarget.scrollTop < 80 && hasMoreMessages && !isLoadingOlderRef.current) {
      void loadOlderMessages();
    }
  };

  const isStopVisible = isSending || isAssistantTyping;

  const isViewOnlyShare = shareInfo?.permission === 'view_only' || shareInfo?.revoked === true;

  const canSend = useMemo(() => {
    const hasText = query.trim().length > 0;
    if (isViewOnlyShare) return false;
    return !isStopVisible && !isUploadingFile && !pendingStorageChoice && hasText;
  }, [isStopVisible, isUploadingFile, pendingStorageChoice, query, isViewOnlyShare]);

  const handleRemoveStagedFile = (localId: string) => {
    setStagedFiles((prev) => prev.filter((f) => f.localId !== localId));
  };

  const showStorageQuotaToast = async () => {
    try {
      const inv = await listUserFilesInventory();
      const lines = inv.slice(0, 12).map(
        (r) => `• ${r.filename} (${(r.size_bytes / (1024 * 1024)).toFixed(1)} MB) — session ${r.session_id.slice(0, 8)}…`,
      );
      toast.error(
        'Storage limit reached (5 GB). Delete some files and try again.\n\n' +
          (lines.length ? `Recent files:\n${lines.join('\n')}` : ''),
      );
    } catch {
      toast.error('Storage limit reached (5 GB). Delete some files and try again.');
    }
  };

  /** Upload staged files to server. Returns uploaded metadata only — does not mutate composer state. */
  const uploadStagedFiles = async (
    importMode: ImportMode,
    filesToUpload: { localId: string; file: File; filename: string }[],
  ): Promise<{ id: string; filename: string }[]> => {
    if (filesToUpload.length === 0) return [];

    setIsUploadingFile(true);
    setFileUploadProgress({ done: 0, total: filesToUpload.length, filename: filesToUpload[0].filename });

    try {
      let sid = sessionId;
      if (!sid) {
        const cr = await createSession(selectedProject?.id || propProjectId || null);
        if (!cr.success || !cr.session_id) {
          toast.error('Could not create a chat session for this upload');
          throw new Error('session_create_failed');
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

      const uploaded: { id: string; filename: string }[] = [];
      let quotaToastShown = false;

      const results = await Promise.allSettled(
        filesToUpload.map((staged) =>
          uploadSessionFile(
            sid!,
            staged.file,
            importMode,
            selectedProject?.id || propProjectId || null,
          ),
        ),
      );

      for (let i = 0; i < results.length; i++) {
        const result = results[i];
        const staged = filesToUpload[i];
        setFileUploadProgress({ done: i + 1, total: filesToUpload.length, filename: staged.filename });

        if (result.status === 'fulfilled') {
          const up = result.value.file;
          uploaded.push({ id: up.id, filename: up.filename });
          continue;
        }

        const e = result.reason as Error & { code?: string };
        if (e.code === 'storage_quota_exceeded' || /5\s*GB|storage limit/i.test(e.message || '')) {
          if (!quotaToastShown) {
            quotaToastShown = true;
            await showStorageQuotaToast();
          }
        } else {
          toast.error(e instanceof Error ? e.message : `Failed to upload ${staged.filename}`);
        }
      }

      if (sid && uploaded.length > 0) {
        const uploadedIds = new Set(uploaded.map((u) => u.id));
        listSessionFiles(sid)
          .then((files) => {
            setSessionFiles(files);
            // Auto-scope this turn to the files just uploaded (intent: ask about them).
            // Only the new files — don't re-add ones the user deliberately unticked.
            const justUploaded: DataSource[] = files
              .filter((f) => uploadedIds.has(f.id))
              .map((f) => ({ type: 'file', id: f.id, filename: f.filename, mime_type: f.mime_type, uploaded_at: f.uploaded_at ?? null }));
            setActiveDataSources((prev) => {
              const have = new Set(prev.map((s) => s.id));
              return [...prev, ...justUploaded.filter((s) => !have.has(s.id))];
            });
          })
          .catch(() => {});
      }

      return uploaded;
    } finally {
      setIsUploadingFile(false);
      setFileUploadProgress(null);
    }
  };

  /** Stage file locally — upload on Send sends the original file (Excel kept for formatting + SQL import on BE). */
  const stageFileForUpload = (file: File) => {
    const localId = `staged-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setStagedFiles((prev) => [...prev, { localId, file, filename: file.name }]);
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // allow re-selecting same file
    e.target.value = '';
    if (!file) return;
    stageFileForUpload(file);
  };

  // Load session when sessionId from URL (propSessionId) is set. Must run when URL has
  // a session (e.g. /chat/87c3eb73) including on full reload, so we load whenever
  // propSessionId is present — not only when it differs from state (on reload state
  // is initialized from the same prop, so propSessionId === sessionId and we'd skip loading).
  useEffect(() => {
    const loadSession = async (sid: string) => {
      try {
        setIsSessionLoading(true);
        const [info, page] = await Promise.all([getSession(sid), getMessages(sid)]);
        if (info.success) {
          setSessionDb(getDbInfoFromSessionResponse(info));
          const sqlActionStates = getSqlActionStatesFromSessionResponse(info);
          setMessages(convertMessages(page.messages, sid, sqlActionStates));
          setOldestCursor(page.next_cursor);
          setHasMoreMessages(page.has_more);
          setStagedFiles([]);
          setSessionId(sid);
          setShareInfo(info.share_info ?? null);
          onSessionIdChange?.(sid);
          saveLastSession(sid, selectedProject?.id ?? null);
        }
      } catch (err) {
        console.error('Failed to load session:', err);
        toast.error('Failed to load chat history');
      } finally {
        setIsSessionLoading(false);
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
      setStagedFiles([]);
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
    // Prepending older messages (scroll-up) must not yank the view to the bottom.
    if (skipAutoScrollRef.current) {
      skipAutoScrollRef.current = false;
      return;
    }
    scrollToBottom();
  }, [messages]);

  // Fetch session files for the DataSource selector whenever session changes
  useEffect(() => {
    if (!sessionId) {
      setSessionFiles([]);
      setActiveDataSources([]);
      setSessionDb(null);
      return;
    }
    listSessionFiles(sessionId)
      .then((files) => {
        setSessionFiles(files);
        const fileIdSet = new Set(files.map((f) => f.id));
        // Default scope is the database (empty selection). Only carry over file picks that
        // still exist in this session; file ids are session-scoped.
        setActiveDataSources((prev) => prev.filter((s) => fileIdSet.has(s.id)));
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
    setIsSending(true);
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
        activeFileIds: scopedFileIds(getActiveFileIds(activeDataSources)),
      });
      setStreamingStage(null);
      // ChatResponse is a discriminated union; downstream code reads optional
      // tool_events / pending_workflow_resume that only exist on success. Keep
      // the original behaviour of treating the payload as a loose object.
      const res = finalRes as any;
      if ((res.response && res.response.trim().length > 0) || readCharts(res.tool_events).length > 0) {
        setIsAssistantTyping(true);
        setMessages((prev) => [
          ...prev,
          {
            text: buildAssistantTextFromSqlPreview(
              (res.response ?? '').trim(),
              readSqlPreview((res as any).tool_events),
            ),
            isUser: false,
            ...(() => {
              const pendingResume = !!(res as { pending_workflow_resume?: boolean }).pending_workflow_resume;
              const sqlAction = resolveSqlExecuteAction((res as any).tool_events, pendingResume);
              return {
                sqlToExecute: sqlAction.sqlToExecute,
                sqlActionState: sqlAction.sqlActionState,
                workflowResumePending: pendingResume,
              };
            })(),
            exportToExcel: readFileExport((res as any).tool_events),
            charts: readCharts((res as any).tool_events),
            schemaPreview: readSchemaPreview((res as any).tool_events),
            schemaLocked: false,
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
      setIsSending(false);
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
    setIsSending(false);
    setIsAssistantTyping(false);
    setStreamingStage(null);
  };

  /** The three mutually-exclusive destinations for an uploaded file's data, and how each
   *  is presented in the storage-choice prompt. */
  const IMPORT_MODE_META: Record<
    ImportMode,
    { icon: React.ReactNode; bg: string; color: string; title: string; desc: string }
  > = {
    project_db: { icon: <Icons.Database size={17} />, bg: 'var(--green-soft)', color: 'var(--green-ink)', title: 'Save to database', desc: "Store this file's data in your project database so you can query it anytime." },
    qa: { icon: <Icons.Question size={17} />, bg: 'var(--surface-3)', color: 'var(--text-soft)', title: 'Q&A only', desc: "Ask about this file now — don't store it in the database." },
    excel: { icon: <Icons.Pencil size={17} />, bg: 'var(--accent-soft)', color: 'var(--accent-ink)', title: 'Edit in Excel', desc: 'Let the assistant open and edit this workbook with the Excel tools.' },
  };

  /** Which destinations make sense for the staged batch. All tabular formats (CSV/TSV/XLS/XLSX)
   *  support every mode — non-xlsx is converted to .xlsx for the Excel tools server-side.
   *  project_db is offered only inside a real project. */
  const availableImportModes = (
    files: { filename: string }[],
    canUseProjectDb: boolean,
  ): ImportMode[] => {
    const anyTabular = files.some((f) => /\.(csv|tsv|txt|xlsx|xlsm|xls|xlsb|ods|xltx|xltm)$/i.test(f.filename));
    if (!anyTabular) return [];
    const modes: ImportMode[] = [];
    if (canUseProjectDb) modes.push('project_db');
    modes.push('qa', 'excel');
    return modes;
  };

  /** Render the user's turn immediately (optimistic) with file chips from local
   *  staged state, then clear the composer. Called before any network round-trip. */
  const showUserTurn = (text: string) => {
    const attachments = stagedFiles.map((f) => ({ name: f.filename }));
    setMessages((prev) => [
      ...prev,
      { text, isUser: true, ...(attachments.length > 0 ? { attachments } : {}) },
    ]);
    setQuery('');
    setInputKey((k) => k + 1);
  };

  const handleSend = async () => {
    if (isStopVisible || isUploadingFile) return;
    const displayText = query.trim();
    if (!displayText) return;

    // project_db needs a real project (the session sandbox / Excel modes don't).
    const canUseProjectDb = !!(selectedProject?.id || propProjectId);
    const modes = stagedFiles.length > 0 ? availableImportModes(stagedFiles, canUseProjectDb) : [];

    // Staged a file we can't import (not CSV/Excel) → refuse before rendering the turn.
    if (stagedFiles.length > 0 && modes.length === 0) {
      toast.error('Unsupported file type. Import supports CSV and Excel files.');
      return;
    }

    showUserTurn(displayText);

    // More than one possible destination → ask which one first; the upload+send resumes
    // in handleStorageChoice() once the user picks.
    if (modes.length > 1) {
      pendingSendPayloadRef.current = displayText;
      setPendingStorageChoice(true);
      return;
    }

    // Exactly one possible destination → no need to ask; upload with it then send.
    if (modes.length === 1) {
      const captured = [...stagedFiles];
      let uploaded: { id: string; filename: string }[];
      try {
        uploaded = await uploadStagedFiles(modes[0], captured);
      } catch (err) {
        if (err instanceof Error && err.message === 'session_create_failed') return;
        throw err;
      }
      if (uploaded.length === 0) return; // upload failed → don't send a dangling turn
      setStagedFiles([]);
      // Files are bound to the session server-side; the user text is sent as-is.
    }

    await doSend(displayText);
  };

  /** Called after user picks an import destination — upload staged files then send. */
  const handleStorageChoice = async (mode: ImportMode) => {
    const captured = [...stagedFiles];
    setStagedFiles([]);
    setPendingStorageChoice(false);
    const displayText = pendingSendPayloadRef.current ?? '';
    pendingSendPayloadRef.current = null;

    let uploaded: { id: string; filename: string }[] = [];
    try {
      uploaded = await uploadStagedFiles(mode, captured);
    } catch (err) {
      if (err instanceof Error && err.message === 'session_create_failed') {
        setStagedFiles(captured);
        setPendingStorageChoice(true);
        pendingSendPayloadRef.current = displayText;
        return;
      }
      throw err;
    }

    if (captured.length > 0 && uploaded.length === 0) {
      setStagedFiles(captured);
      setPendingStorageChoice(true);
      pendingSendPayloadRef.current = displayText;
      return;
    }

    // Uploaded files are bound to the session server-side; send the user text as-is.
    void uploaded;
    await doSend(displayText);
  };

  /** Start a fresh chat inside the current project (from the project view). */
  const handleNewChatInProject = async () => {
    const pid = selectedProject?.id || propProjectId;
    if (!pid) return;
    try {
      const cr = await createSession(pid);
      if (cr.success && cr.session_id) {
        saveLastSession(cr.session_id, pid);
        window.history.pushState({}, '', `/chat/${pid}/${cr.session_id}`);
        window.dispatchEvent(new PopStateEvent('popstate'));
        onSessionIdChange?.(cr.session_id);
      } else {
        toast.error('Failed to create new chat');
      }
    } catch {
      toast.error('Failed to create new chat');
    }
  };

  const handleRefreshResponse = async (aiIndex: number) => {
    const userIndex = aiIndex - 1;
    if (userIndex < 0) return;
    const userMsg = messages[userIndex];
    if (!userMsg?.isUser) return;

    setIsSending(true);
    try {
      // Files are bound to the session server-side; pass their ids via active_file_ids
      // (no marker text embedded in the message anymore).
      const refreshFileIds = (userMsg.attachments || [])
        .map((a) => a.fileId)
        .filter((id): id is string => !!id);
      const res = await sendMessageWithStream(userMsg.text, sessionId, selectedProject?.id || null, {
        activeFileIds: scopedFileIds(refreshFileIds.length ? refreshFileIds : getActiveFileIds(activeDataSources)),
      });
      const resText = res.response;
      if ((resText && resText.trim().length > 0) || readCharts((res as any).tool_events).length > 0) {
        setMessages((prev) => {
          const updated = [...prev];
          updated[aiIndex] = {
            text: buildAssistantTextFromSqlPreview(
              (resText ?? '').trim(),
              readSqlPreview((res as any).tool_events),
            ),
            isUser: false,
            ...(() => {
              const pendingResume = !!(res as { pending_workflow_resume?: boolean }).pending_workflow_resume;
              const sqlAction = resolveSqlExecuteAction((res as any).tool_events, pendingResume);
              return {
                sqlToExecute: sqlAction.sqlToExecute,
                sqlActionState: sqlAction.sqlActionState,
                workflowResumePending: pendingResume,
              };
            })(),
            exportToExcel: readFileExport((res as any).tool_events),
            charts: readCharts((res as any).tool_events),
            schemaPreview: readSchemaPreview((res as any).tool_events),
          };
          return updated;
        });
      } else if (!res.success) {
        toast.error(`Error: ${res.error || 'Failed to refresh response'}`);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to refresh response';
      toast.error(`Error: ${message}`);
    } finally {
      setIsSending(false);
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

  const handleSchemaTableNameChange = (aiIndex: number, name: string) => {
    setMessages((prev) => {
      const updated = [...prev];
      const msg = updated[aiIndex];
      if (!msg?.schemaPreview) return prev;
      updated[aiIndex] = {
        ...msg,
        schemaPreview: { ...msg.schemaPreview, tableName: name },
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
    if (!msg?.schemaPreview || isSending) return;

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

    setIsSending(true);
    try {
      const res = await resumeWorkflow(
        sessionId,
        true,
        selectedProject?.id || null,
        `Confirm schema table ${schema.tableName}`,
        schema,  // user-edited columns/types/constraints/table name → server rebuilds the SQL
      );
      if (res.success) {
        const resText = res.response ?? '';
        setMessages((prev) => [
          ...prev,
          {
            text: buildAssistantTextFromSqlPreview(
              (resText ?? '').trim(),
              readSqlPreview((res as any).tool_events),
            ),
            isUser: false,
            ...(() => {
              const pendingResume = !!(res as { pending_workflow_resume?: boolean }).pending_workflow_resume;
              const sqlAction = resolveSqlExecuteAction((res as any).tool_events, pendingResume);
              return {
                sqlToExecute: sqlAction.sqlToExecute,
                sqlActionState: sqlAction.sqlActionState,
                workflowResumePending: pendingResume,
              };
            })(),
            exportToExcel: readFileExport((res as any).tool_events),
            schemaPreview: readSchemaPreview((res as any).tool_events),
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
      setIsSending(false);
    }
  };

  const handleExecuteSql = async (aiIndex: number) => {
    const msg = messages[aiIndex];
    if (!msg || !msg.sqlToExecute || isSending || msg.sqlActionState === 'running' || msg.sqlActionState === 'executed' || msg.sqlActionState === 'cancelled') return;

    // Show a loading state while the query runs (reference SqlPreview "running").
    setMessages((prev) => {
      const updated = [...prev];
      const current = updated[aiIndex];
      if (current) {
        updated[aiIndex] = { ...current, sqlActionState: 'running' };
      }
      return updated;
    });

    setIsSending(true);
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
        const cleanedRaw = (resText ?? '').trim();
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
                readSqlPreview((res as any).tool_events),
              ),
              isUser: false,
              ...(() => {
                const pendingResume = !!(res as { pending_workflow_resume?: boolean }).pending_workflow_resume;
                const sqlAction = resolveSqlExecuteAction((res as any).tool_events, pendingResume);
                return {
                  sqlToExecute: sqlAction.sqlToExecute,
                  sqlActionState: sqlAction.sqlActionState,
                  workflowResumePending: pendingResume,
                };
              })(),
              exportToExcel: readFileExport((res as any).tool_events),
              schemaPreview: readSchemaPreview((res as any).tool_events),
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
      setIsSending(false);
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
      setStagedFiles([]);
      onSessionIdChange?.(null);
    }
    prevProjectIdRef.current = currentId;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProject?.id]);

  // Function to load project sessions
  const loadProjectSessions = async () => {
    if (!selectedProject) {
      setProjectSessions([]);
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
      }
    } catch (err) {
      console.error('Failed to load project sessions:', err);
    }
  };

  const [deletingProjectSessionId, setDeletingProjectSessionId] = useState<string | null>(null);
  const handleDeleteProjectSession = async (session: SessionInfo) => {
    const name = formatSessionName(session);
    if (!(await confirm({ title: 'Delete chat?', message: `Delete "${name}"? This removes the chat and its files. This can't be undone.`, confirmLabel: 'Delete', danger: true }))) return;
    setDeletingProjectSessionId(session.session_id);
    try {
      await deleteChatSession(session.session_id);
      setProjectSessions((prev) => prev.filter((s) => s.session_id !== session.session_id));
      if (sessionId === session.session_id && selectedProject) {
        window.history.pushState({}, '', `/chat/${selectedProject.id}`);
        window.dispatchEvent(new PopStateEvent('popstate'));
        if (onSessionIdChange) onSessionIdChange(null);
      }
      window.dispatchEvent(new Event('projectSessionsUpdated'));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete chat');
    } finally {
      setDeletingProjectSessionId(null);
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
        setIsSessionLoading(true);
        const [info, page] = await Promise.all([getSession(sid), getMessages(sid)]);
        if (info.success) {
          setSessionDb(getDbInfoFromSessionResponse(info));
          const sqlActionStates = getSqlActionStatesFromSessionResponse(info);
          setMessages(convertMessages(page.messages, sid, sqlActionStates));
          setOldestCursor(page.next_cursor);
          setHasMoreMessages(page.has_more);
          setStagedFiles([]);
          setSessionId(sid);
          setShareInfo(info.share_info ?? null);
          onSessionIdChange?.(sid);
        }
      } catch {
        hasRestoredSessionRef.current = false;
      } finally {
        setIsSessionLoading(false);
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

  // Show the project landing view (header + "New chat in this project" + chats list)
  // whenever a project is open with no active session — even if it has 0 chats yet.
  const showProjectLanding = selectedProject && !sessionId && messages.length === 0;

  // Check if we're in "empty" state: no messages (regardless of project or sessionId)
  // This includes: 
  // - Project selected but no chat history yet (show empty state with project in header)
  // - No project and no chat
  // - New session created but no messages sent yet
  const isEmptyState = messages.length === 0 && !showProjectLanding;

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
  const hasStagedFiles = stagedFiles.length > 0;

  const composer = (
    <div className="card soft-shadow" style={{ borderRadius: 'var(--r-lg)', padding: '14px 16px 12px', maxWidth: 760, margin: '0 auto', width: '100%' }}>
      <input
        ref={fileInputRef}
        type="file"
        style={{ display: 'none' }}
        multiple={false}
        accept=".xlsx,.xlsm,.xls,.xlsb,.ods,.xltx,.xltm,.csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,application/vnd.oasis.opendocument.spreadsheet"
        onChange={handleFileInputChange}
      />

      {/* Upload progress (after Send, before chat request) */}
      {isUploadingFile && fileUploadProgress && (
        <div
          className="scale-in"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            marginBottom: 10,
            padding: '8px 10px',
            borderRadius: 'var(--r-sm)',
            border: '1px solid var(--accent-soft-2)',
            background: 'var(--accent-soft)',
            color: 'var(--accent-ink)',
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          <span style={{ fontSize: 18, lineHeight: 1, flexShrink: 0 }}>…</span>
          <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            Uploading {fileUploadProgress.done} of {fileUploadProgress.total}
            {fileUploadProgress.filename ? `: ${fileUploadProgress.filename}` : ''}…
          </span>
        </div>
      )}

      {/* Staged files (not yet uploaded) */}
      {!pendingStorageChoice && !isUploadingFile && hasStagedFiles && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
          {stagedFiles.map((f) => (
            <div key={f.localId} className="scale-in" style={{ display: 'inline-flex', alignItems: 'center', gap: 9, padding: '7px 9px 7px 8px', borderRadius: 'var(--r-sm)', border: '1px dashed var(--border-strong)', background: 'var(--surface-2)' }}>
              <FileTypeBadge filename={f.filename} mimeType={f.file.type} size={28} radius={7} style={{ opacity: 0.7 }} />
              <span style={{ fontSize: 13, fontWeight: 600, maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.filename}</span>
              <button
                type="button"
                disabled={isViewOnlyShare || pendingStorageChoice}
                onClick={() => handleRemoveStagedFile(f.localId)}
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
        disabled={isViewOnlyShare || isUploadingFile}
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
            disabled={isViewOnlyShare || isUploadingFile}
          />
          {/* Data source selector — files only; empty selection = ask the database. */}
          {(() => {
            const sources = buildDataSources(sessionFiles);
            return sources.length >= 1 ? (
              <div style={{ marginBottom: -12 }}>
                <DataSourceBar
                  sources={sources}
                  active={activeDataSources}
                  onToggle={handleToggleDataSource}
                  dbLabel={primaryDbLabel}
                />
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
        <span style={{ fontSize: 14.5, fontWeight: 700, color: 'var(--text)' }}>How do you want to use this file?</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12 }}>
        {availableImportModes(stagedFiles, !!(selectedProject?.id || propProjectId)).map((mode) => {
          const opt = IMPORT_MODE_META[mode];
          return (
          <button
            key={mode}
            type="button"
            onClick={() => void handleStorageChoice(mode)}
            disabled={isUploadingFile}
            className="focusable"
            style={{ display: 'flex', alignItems: 'flex-start', gap: 12, textAlign: 'left', padding: '12px 14px', borderRadius: 'var(--r-sm)', border: '1px solid var(--border)', background: 'var(--surface)', transition: 'all .13s', opacity: isUploadingFile ? 0.6 : 1, cursor: isUploadingFile ? 'default' : 'pointer' }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.background = 'var(--accent-soft)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.background = 'var(--surface)'; }}
          >
            <span style={{ width: 32, height: 32, borderRadius: 9, flexShrink: 0, display: 'grid', placeItems: 'center', background: opt.bg, color: opt.color }}>{opt.icon}</span>
            <span>
              <span style={{ display: 'block', fontSize: 14, fontWeight: 700 }}>{opt.title}</span>
              <span style={{ display: 'block', fontSize: 12.5, color: 'var(--text-muted)', marginTop: 1 }}>{opt.desc}</span>
            </span>
          </button>
          );
        })}
      </div>
    </div>
  ) : null;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, background: 'var(--bg)' }}>
      {shareBanner}

      {/* Conversation */}
      {messages.length > 0 && (
        <div ref={scrollContainerRef} onScroll={handleMessagesScroll} style={{ flex: 1, overflowY: 'auto' }}>
          <div style={{ maxWidth: 760, margin: '0 auto', padding: '32px 24px 24px' }}>
            <MessageList
              messages={messages}
              onRefreshResponse={(idx) => void handleRefreshResponse(idx)}
              onExecuteSql={(idx) => void handleExecuteSql(idx)}
              onCancelSql={(idx) => void handleCancelSql(idx)}
              onExportFile={(idx) => void handleExportExcel(idx)}
              onSchemaTypeChange={handleSchemaTypeChange}
              onSchemaTableNameChange={handleSchemaTableNameChange}
              onToggleSchemaOptions={handleToggleSchemaOptions}
              onSchemaOptionChange={handleSchemaOptionChange}
              onConfirmSchema={(idx) => void handleConfirmSchema(idx)}
              onAssistantTypingChange={setIsAssistantTyping}
              typingStopSignal={typingStopSignal}
              onSaveChart={selectedProject ? async (recipe: ChartRecipe): Promise<boolean> => {
                try {
                  const res = await saveChart(selectedProject.id, recipe);
                  if (res.success) {
                    const already = !!(res.chart as { already?: boolean } | undefined)?.already;
                    toast.success(already ? 'Already in the dashboard' : 'Saved to project dashboard');
                    return true;
                  }
                  toast.error(res.detail || 'Could not save chart');
                  return false;
                } catch {
                  toast.error('Could not save chart');
                  return false;
                }
              } : undefined}
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
      ) : showProjectLanding ? null : (
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

      {/* Project landing: header + new-chat CTA + chats list (or empty hint) */}
      {showProjectLanding && (
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
            {projectSessions.length === 0 ? (
              <div style={{ fontSize: 14.5, color: 'var(--text-muted)', padding: '4px 2px' }}>
                No chats yet — start one with “New chat in this project”.
              </div>
            ) : (
            <div className="card" style={{ overflow: 'hidden' }}>
              {projectSessions.map((session, index) => {
                const deleting = deletingProjectSessionId === session.session_id;
                return (
                <div key={session.session_id} style={{ position: 'relative', display: 'flex', alignItems: 'center', borderTop: index ? '1px solid var(--border)' : 'none' }}>
                  <button
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
                    style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 13, padding: '14px 50px 14px 18px', textAlign: 'left', background: 'transparent', border: 'none' }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                  >
                    <span style={{ width: 34, height: 34, borderRadius: 9, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
                      <Icons.NewChat size={16} />
                    </span>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ display: 'block', fontSize: 14.5, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{formatSessionName(session)}</span>
                    </span>
                    {session.created_at && (
                      <span style={{ fontSize: 12, color: 'var(--text-faint)', flexShrink: 0 }}>{formatDate(session.created_at)}</span>
                    )}
                  </button>
                  <button
                    type="button"
                    className="focusable"
                    aria-label={`Delete chat ${formatSessionName(session)}`}
                    title="Delete chat"
                    disabled={deleting}
                    onClick={(e) => { e.stopPropagation(); void handleDeleteProjectSession(session); }}
                    style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', width: 30, height: 30, display: 'grid', placeItems: 'center', borderRadius: 7, border: 'none', background: 'transparent', color: 'var(--text-faint)', cursor: deleting ? 'not-allowed' : 'pointer', flexShrink: 0 }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-3)'; e.currentTarget.style.color = 'var(--danger)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-faint)'; }}
                  >
                    <Icons.Trash size={15} />
                  </button>
                </div>
                );
              })}
            </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

