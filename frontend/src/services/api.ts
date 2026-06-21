// Prefer relative "/api/*" so Vite proxy can handle same-origin cookies.
// You can override with VITE_API_URL if you don't want to use the proxy.
const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export type ToolEvent = {
  tool: string;
  type: string;
  payload?: Record<string, unknown>;
};

export type ChatResponse = {
  success: boolean;
  response?: string;
  error?: string;
  session_id?: string | null;
  tool_events?: ToolEvent[];
  pending_workflow_resume?: boolean;
  warnings?: Record<string, unknown>[];
};

export type SessionInfo = {
  session_id: string;
  session_name?: string;
  created_at?: string;
  message_count?: number;
  project_id?: string | null;
};

export type SessionsResponse =
  | { success: true; sessions: SessionInfo[] }
  | { success: false; error: string };

export type CreateSessionResponse =
  | { success: true; session_id: string | null; session_info: unknown }
  | { success: false; error: string };

export type SessionShareInfo = {
  permission: 'view_only' | 'read_data' | 'edit_data';
  revoked: boolean;
  share_id: string;
};

/** A single message row from GET /api/sessions/{id}/messages. */
export type SessionMessage = {
  id?: string;
  role: string;
  content?: string;
  tool_events?: ToolEvent[];
  created_at?: string;
  pending_workflow_resume?: boolean;
};

/** Session metadata only — messages are loaded separately via getMessages(). */
export type GetSessionResponse =
  | {
      success: true;
      session_info: unknown;
      share_info: SessionShareInfo | null;
    }
  | { success: false; error: string };

/** One cursor page of messages (oldest→newest). Pass `next_cursor` back as `before` for older. */
export type MessagesPage = {
  success: true;
  messages: SessionMessage[];
  has_more: boolean;
  next_cursor: string | null;
};

export type HealthResponse = { status: 'ok'; agent_initialized: boolean };

export function url(path: string) {
  return API_BASE_URL.startsWith('http') ? `${API_BASE_URL}${path}` : path;
}

export type StreamEvent =
  | { type: 'started' }
  | { type: 'stage'; stage: string; status: 'running' | 'completed' | 'error'; message?: string }
  | { type: 'final'; data: ChatResponse }
  | { type: 'error'; status_code?: number; message: string };

export type StreamHandlers = {
  onEvent: (e: StreamEvent) => void;
  signal?: AbortSignal;
};

/**
 * Stream chat response via SSE. Calls ``onEvent`` for every parsed event.
 * Resolves when the server closes the stream (after ``final`` or ``error``).
 *
 * Frontend uses fetch + ReadableStream because EventSource is GET-only and we
 * need to POST the chat payload.
 */
export async function sendMessageStream(
  message: string,
  sessionId: string | null,
  projectId: string | null,
  handlers: StreamHandlers,
  activeFileIds?: string[] | null,
): Promise<void> {
  const response = await fetch(url('/api/chat'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      project_id: projectId,
      active_file_ids: activeFileIds?.length ? activeFileIds : null,
    }),
    signal: handlers.signal,
  });

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => '');
    throw new Error(`stream HTTP ${response.status}: ${text}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  // SSE frames are separated by blank lines. Each frame can have multiple
  // ``key: value`` lines; we only care about ``data:`` (the JSON payload).
  // The ``event:`` line is ignored — type is encoded inside the JSON.
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const dataLines = frame
        .split('\n')
        .filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).trimStart());
      if (dataLines.length === 0) continue;
      try {
        const parsed = JSON.parse(dataLines.join('\n')) as StreamEvent;
        handlers.onEvent(parsed);
      } catch {
        // Malformed frame — skip
      }
    }
  }
}

/**
 * Stream-based chat call that awaits the terminal ``final`` event and returns
 * the same ChatResponse shape as the old blocking ``sendMessage``. Lets call
 * sites that don't care about intermediate stage events still benefit from
 * SSE (one transport, one backend code path).
 *
 * Pass ``onStage`` to surface progress in a loading indicator; omit it when
 * you only need the final result.
 */
export async function sendMessageWithStream(
  message: string,
  sessionId: string | null,
  projectId: string | null,
  options?: { onStage?: (stage: string) => void; signal?: AbortSignal; activeFileIds?: string[] | null },
): Promise<ChatResponse> {
  let finalRes: ChatResponse | null = null;
  let streamErr: { status?: number; message: string } | null = null;
  await sendMessageStream(message, sessionId, projectId, {
    signal: options?.signal,
    onEvent: (e: StreamEvent) => {
      if (e.type === 'stage') {
        if (e.message && options?.onStage) options.onStage(e.message);
      } else if (e.type === 'final') {
        finalRes = e.data;
      } else if (e.type === 'error') {
        streamErr = { status: e.status_code, message: e.message };
      }
    },
  }, options?.activeFileIds);
  if (streamErr !== null) {
    throw new Error((streamErr as { message: string }).message || 'Streaming chat failed');
  }
  if (finalRes === null) {
    throw new Error('Stream ended without a final event');
  }
  return finalRes;
}

export async function resumeWorkflow(
  sessionId: string,
  approved: boolean,
  projectId: string | null = null,
  userVisibleMessage: string | null = null,
  editedSchema: unknown = null,
  signal?: AbortSignal
): Promise<ChatResponse> {
  const response = await fetch(url('/api/chat/resume'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      approved,
      project_id: projectId,
      user_visible_message: userVisibleMessage,
      // create_table: the user-edited schema (columns/types/constraints/table name); the
      // server rebuilds + re-verifies the CREATE SQL from it. null for other workflows.
      edited_schema: editedSchema,
    }),
    signal,
  });
  const data = (await response.json()) as ChatResponse & { error?: string };
  if (!response.ok) {
    throw new Error((data as any).error || 'Failed to resume workflow');
  }
  return data;
}

export async function getSessions(projectId: string | null = null, unassignedOnly: boolean = false): Promise<SessionsResponse> {
  const params = new URLSearchParams();
  if (projectId) {
    params.append('project_id', projectId);
  }
  if (unassignedOnly) {
    params.append('unassigned_only', 'true');
  }
  const queryParams = params.toString();
  const urlPath = queryParams ? `/api/sessions?${queryParams}` : '/api/sessions';
  const response = await fetch(url(urlPath), { method: 'GET', credentials: 'include', headers: { 'Content-Type': 'application/json' } });
  if (!response.ok) throw new Error('Failed to get sessions');
  return (await response.json()) as SessionsResponse;
}

export async function createSession(projectId: string | null = null): Promise<CreateSessionResponse> {
  const response = await fetch(url('/api/sessions'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId }),
  });
  if (!response.ok) throw new Error('Failed to create session');
  return (await response.json()) as CreateSessionResponse;
}

export async function getSession(sessionId: string): Promise<GetSessionResponse> {
  const response = await fetch(url(`/api/sessions/${encodeURIComponent(sessionId)}`), {
    method: 'GET',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) throw new Error('Failed to get session');
  return (await response.json()) as GetSessionResponse;
}

/**
 * Cursor-paginated messages for a session (returned oldest→newest).
 * Omit `before` for the latest page; pass a previous page's `next_cursor` to load older.
 */
export async function getMessages(
  sessionId: string,
  before?: string | null,
  limit = 30,
): Promise<MessagesPage> {
  const params = new URLSearchParams();
  if (before) params.append('before', before);
  params.append('limit', String(limit));
  const response = await fetch(
    url(`/api/sessions/${encodeURIComponent(sessionId)}/messages?${params.toString()}`),
    { method: 'GET', credentials: 'include', headers: { 'Content-Type': 'application/json' } },
  );
  if (!response.ok) throw new Error('Failed to load messages');
  return (await response.json()) as MessagesPage;
}

export async function healthCheck(): Promise<HealthResponse> {
  const response = await fetch(url('/api/health'), { method: 'GET', credentials: 'include' });
  if (!response.ok) throw new Error('Health check failed');
  return (await response.json()) as HealthResponse;
}

export type ProjectItem = {
  id: string;
  name: string;
  description?: string;
  created_at?: string;
};

export type GetProjectsResponse =
  | { success: true; projects: ProjectItem[] }
  | { success: false; error: string };

export async function getProjects(): Promise<GetProjectsResponse> {
  const response = await fetch(url('/api/projects'), {
    method: 'GET',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const data = (await response.json()) as { error?: string };
    return { success: false, error: data.error ?? 'Failed to get projects' };
  }
  return (await response.json()) as GetProjectsResponse;
}

export type CreateProjectRequest = {
  name: string;
  description?: string;
  db_url: string;
};

export type CreateProjectResponse =
  | { success: true; project: { id: string; name: string; description?: string; created_at?: string } }
  | { success: false; error: string };

export async function createProject(name: string, description?: string): Promise<CreateProjectResponse> {
  const response = await fetch(url('/api/projects'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    // db_url cố tình bỏ: backend tự sinh SQLite khi tạo project
    body: JSON.stringify({ name, description }),
  });
  if (!response.ok) {
    const data = (await response.json()) as { error?: string };
    throw new Error(data.error || 'Failed to create project');
  }
  return (await response.json()) as CreateProjectResponse;
}

export type DeleteProjectResponse =
  | { success: true; deleted_sessions?: number }
  | { success: false; error: string };

/** Delete a project plus its chats, files, temp DBs and SQLite database. */
export async function deleteProject(id: string): Promise<DeleteProjectResponse> {
  const response = await fetch(url(`/api/projects/${encodeURIComponent(id)}`), {
    method: 'DELETE',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const data = (await response.json().catch(() => ({}))) as { error?: string };
    return { success: false, error: data.error ?? 'Failed to delete project' };
  }
  return (await response.json()) as DeleteProjectResponse;
}

// ----- Admin dashboard -----

export type AdminUser = {
  id: number;
  name: string | null;
  email: string | null;
  created_at: string | null;
  is_admin: boolean;
  disabled: boolean;
  disabled_at: string | null;
  project_count: number;
  session_count: number;
  storage_bytes: number;
};

export type AdminStats = {
  total_users: number;
  disabled_users: number;
  admin_users: number;
  total_projects: number;
  total_sessions: number;
  total_storage_bytes: number;
};

export async function getAdminUsers(): Promise<AdminUser[]> {
  const response = await fetch(url('/api/admin/users'), { credentials: 'include' });
  if (!response.ok) throw new Error('Failed to load users');
  const data = (await response.json()) as { success: boolean; users?: AdminUser[] };
  return data.users ?? [];
}

export async function getAdminStats(): Promise<AdminStats> {
  const response = await fetch(url('/api/admin/stats'), { credentials: 'include' });
  if (!response.ok) throw new Error('Failed to load stats');
  const data = (await response.json()) as { success: boolean; stats: AdminStats };
  return data.stats;
}

/** Disable (lock out) or re-enable a user account. Returns the new disabled state. */
export async function setUserDisabled(userId: number, disabled: boolean): Promise<boolean> {
  const action = disabled ? 'disable' : 'enable';
  const response = await fetch(url(`/api/admin/users/${userId}/${action}`), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const data = (await response.json().catch(() => ({}))) as { detail?: string; error?: string };
    throw new Error(data.detail || data.error || 'Failed to update user');
  }
  const data = (await response.json()) as { disabled: boolean };
  return data.disabled;
}

// ----- Chat session sharing -----

export type SharePermission = 'view_only' | 'read_data' | 'edit_data';

export type ShareRecipientInput = {
  email: string;
  permission: SharePermission;
};

export type ShareRecipientCreated = {
  id: string;
  email: string;
  permission: SharePermission;
  accept_token: string;
  accept_url: string;
};

export type CreateShareResponse = {
  success: true;
  share_id: string;
  session_id: string;
  project_id: string;
  recipients: ShareRecipientCreated[];
};

export async function createShare(
  sessionId: string,
  recipients: ShareRecipientInput[],
  options: { notifyViaEmail?: boolean } = {},
): Promise<CreateShareResponse> {
  const notify = options.notifyViaEmail ?? true;
  const response = await fetch(url(`/api/sessions/${encodeURIComponent(sessionId)}/share`), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, recipients, notify_via_email: notify }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error((data as any).detail || (data as any).error || 'Failed to create share');
  }
  return data as CreateShareResponse;
}

export async function resendShareEmail(recipientId: string): Promise<void> {
  const response = await fetch(
    url(`/api/shares/recipients/${encodeURIComponent(recipientId)}/resend-email`),
    { method: 'POST', credentials: 'include' },
  );
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error((data as any).detail || 'Failed to resend email');
  }
}

export type SentShareRecipient = {
  id: string;
  email: string;
  permission: SharePermission;
  accept_token: string;
  accepted_at: string | null;
  revoked_at: string | null;
  forked_session_id: string | null;
  email_sent_at: string | null;
  email_error: string | null;
};

export type SentShare = {
  share_id: string;
  session_id: string;
  project_id: string;
  session_name: string | null;
  created_at: string;
  revoked_at: string | null;
  recipients: SentShareRecipient[];
};

export async function listSentShares(): Promise<SentShare[]> {
  const response = await fetch(url('/api/shares/sent'), { credentials: 'include' });
  if (!response.ok) throw new Error('Failed to list sent shares');
  const data = await response.json();
  return (data.shares || []) as SentShare[];
}

export type ReceivedShare = {
  recipient_id: string;
  share_id: string;
  permission: SharePermission;
  accept_token: string;
  accepted_at: string | null;
  forked_session_id: string | null;
  session_id: string;
  project_id: string;
  session_name: string | null;
  shared_at: string;
  owner_name: string | null;
  owner_email: string | null;
};

export async function listReceivedShares(): Promise<ReceivedShare[]> {
  const response = await fetch(url('/api/shares/received'), { credentials: 'include' });
  if (!response.ok) throw new Error('Failed to list received shares');
  const data = await response.json();
  return (data.shares || []) as ReceivedShare[];
}

export type SharePreview = {
  recipient_email: string;
  permission: SharePermission;
  session_name: string | null;
  accepted_at: string | null;
  forked_session_id: string | null;
  project_id: string;
  logged_in: boolean;
  email_match: boolean;
};

export async function previewShare(acceptToken: string): Promise<SharePreview> {
  const response = await fetch(url(`/api/shares/by-token/${encodeURIComponent(acceptToken)}`), {
    credentials: 'include',
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error((data as any).detail || 'Failed to load share');
  }
  return data.share as SharePreview;
}

export type AcceptShareResponse = {
  success: true;
  session_id: string;
  project_id: string;
  permission: SharePermission;
  already_accepted: boolean;
};

export async function acceptShare(acceptToken: string): Promise<AcceptShareResponse> {
  const response = await fetch(url(`/api/shares/${encodeURIComponent(acceptToken)}/accept`), {
    method: 'POST',
    credentials: 'include',
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error((data as any).detail || 'Failed to accept share');
  }
  return data as AcceptShareResponse;
}

export async function revokeShare(shareId: string): Promise<void> {
  const response = await fetch(url(`/api/shares/${encodeURIComponent(shareId)}`), {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error((data as any).detail || 'Failed to revoke share');
  }
}

export async function revokeShareRecipient(recipientId: string): Promise<void> {
  const response = await fetch(url(`/api/shares/recipients/${encodeURIComponent(recipientId)}`), {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error((data as any).detail || 'Failed to revoke recipient');
  }
}

export type ExecuteSqlResponse = ChatResponse;

export async function executeSql(
  sql: string,
  actionId: string | null,
  sessionId: string | null = null,
  projectId: string | null = null,
  lockOnly: boolean = false,
  lockState: 'executed' | 'cancelled' | null = null,
): Promise<ExecuteSqlResponse> {
  const response = await fetch(url('/api/sql/execute'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sql, action_id: actionId, session_id: sessionId, project_id: projectId, lock_only: lockOnly, lock_state: lockState }),
  });

  const data = (await response.json()) as ExecuteSqlResponse & { error?: string };
  if (!response.ok) {
    throw new Error((data as any).error || 'Failed to execute SQL');
  }
  return data;
}

export async function exportData(
  tableName: string,
  columns: string = '*',
  whereClause: string | null = null,
  format: 'csv' | 'excel' = 'csv',
  sessionId: string | null = null,
  projectId: string | null = null
): Promise<void> {
  const params = new URLSearchParams();
  params.append('table_name', tableName);
  params.append('columns', columns);
  if (whereClause) params.append('where_clause', whereClause);
  params.append('format', format);
  if (sessionId) params.append('session_id', sessionId);
  if (projectId) params.append('project_id', projectId);

  const response = await fetch(url(`/api/export?${params.toString()}`), {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error((data as { detail?: string }).detail || 'Failed to export data');
  }

  // Get filename from Content-Disposition header or generate one
  const contentDisposition = response.headers.get('Content-Disposition');
  let filename = `${tableName}.${format}`;
  if (contentDisposition) {
    const match = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
    if (match) {
      filename = match[1].replace(/['"]/g, '');
    }
  }

  // Download file
  const blob = await response.blob();
  const blobUrl = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = blobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(blobUrl);
  a.remove();
}


// ----- Session file memory (RAG) -----

export type SessionFileMeta = {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  uploaded_at?: string | null;
};

export async function listSessionFiles(sessionId: string): Promise<SessionFileMeta[]> {
  const response = await fetch(
    url(`/api/files?session_id=${encodeURIComponent(sessionId)}`),
    { credentials: 'include' },
  );
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail || 'Failed to list session files');
  }
  const data = (await response.json()) as { files?: SessionFileMeta[] };
  return data.files ?? [];
}

export type UploadSessionFileResult = {
  file: SessionFileMeta;
};

/** Where an uploaded file's data goes (mutually exclusive):
 *  - project_db: imported into the project's real database
 *  - qa:         imported into the session sandbox for SQL Q&A (not persisted to the real DB)
 *  - excel:      kept as a workbook for the Excel tools to read/edit (no SQL import) */
export type ImportMode = 'project_db' | 'qa' | 'excel';

function uploadErrorMessage(data: unknown): string {
  if (typeof data !== 'object' || data === null) return 'Failed to upload file';
  const d = data as { detail?: unknown };
  const detail = d.detail;
  if (typeof detail === 'string') return detail;
  if (typeof detail === 'object' && detail !== null && 'message' in detail) {
    return String((detail as { message?: string }).message || 'Failed to upload file');
  }
  return 'Failed to upload file';
}

export type FileQuotaInfo = {
  used_bytes: number;
  limit_bytes: number;
  remaining_bytes: number;
  import_used_bytes: number;
  export_used_bytes: number;
};

export async function getFilesQuota(): Promise<FileQuotaInfo> {
  const response = await fetch(url('/api/files/quota'), { credentials: 'include' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error((data as { detail?: string }).detail || 'Failed to load storage quota');
  }
  const w = data as FileQuotaInfo;
  return {
    used_bytes: w.used_bytes,
    limit_bytes: w.limit_bytes,
    remaining_bytes: w.remaining_bytes,
    import_used_bytes: w.import_used_bytes ?? w.used_bytes,
    export_used_bytes: w.export_used_bytes ?? 0,
  };
}

export type UserFileInventoryRow = {
  id: string;
  session_id: string;
  filename: string;
  size_bytes: number;
  uploaded_at?: string | null;
};

export async function listUserFilesInventory(): Promise<UserFileInventoryRow[]> {
  const response = await fetch(url('/api/files/inventory'), { credentials: 'include' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error((data as { detail?: string }).detail || 'Failed to list files');
  }
  return (data as { files?: UserFileInventoryRow[] }).files ?? [];
}

/** Assistant chat exports persisted under ``file_handle/.../export/`` (same shape as import rows). */
export type ExportFileInventoryRow = UserFileInventoryRow;

export async function listExportFilesInventory(): Promise<ExportFileInventoryRow[]> {
  const response = await fetch(url('/api/files/export-inventory'), { credentials: 'include' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error((data as { detail?: string }).detail || 'Failed to list export files');
  }
  return (data as { files?: ExportFileInventoryRow[] }).files ?? [];
}

export async function uploadSessionFile(
  sessionId: string,
  file: File,
  importMode: ImportMode,
  projectId: string | null = null,
): Promise<UploadSessionFileResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('session_id', sessionId);
  form.append('import_mode', importMode);
  if (projectId) form.append('project_id', projectId);
  const response = await fetch(url('/api/files/upload'), {
    method: 'POST',
    credentials: 'include',
    body: form,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const err = new Error(uploadErrorMessage(data)) as Error & {
      status?: number;
      code?: string;
      detail?: unknown;
    };
    err.status = response.status;
    const det = (data as { detail?: { code?: string } }).detail;
    if (typeof det === 'object' && det && typeof det.code === 'string') {
      err.code = det.code;
    }
    err.detail = (data as { detail?: unknown }).detail;
    throw err;
  }
  const wrapped = data as { file: SessionFileMeta };
  return { file: wrapped.file };
}

export async function deleteSessionFile(fileId: string): Promise<void> {
  const response = await fetch(url(`/api/files/${encodeURIComponent(fileId)}`), {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail || 'Failed to delete file');
  }
}

/** Download a session file from ``file_handle/{user}/{session}/import`` or ``…/export``. */
export async function downloadStoredSessionFile(fileId: string): Promise<void> {
  const response = await fetch(url(`/api/files/${encodeURIComponent(fileId)}/download`), {
    method: 'GET',
    credentials: 'include',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail || 'Download failed');
  }
  const contentDisposition = response.headers.get('Content-Disposition');
  let filename = 'export.xlsx';
  if (contentDisposition) {
    const match = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
    if (match) {
      filename = match[1].replace(/['"]/g, '');
    }
  }
  const blob = await response.blob();
  const blobUrl = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = blobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(blobUrl);
  a.remove();
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  const response = await fetch(url(`/api/sessions/${encodeURIComponent(sessionId)}`), {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail || 'Failed to delete session');
  }
}



export type DbConnectResult = { success: boolean; message: string };

/** Status of the user's active external DB. Redacted — never includes the password. */
export type DbStatusResult = {
  success: boolean;
  message: string;
  host?: string | null;
  port?: number | null;
  database?: string | null;
  username?: string | null;
};

export async function connectExternalDb(data: {
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
}): Promise<DbConnectResult> {
  const response = await fetch(url('/api/db/connect'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return response.json() as Promise<DbConnectResult>;
}

export async function disconnectExternalDb(): Promise<DbConnectResult> {
  const response = await fetch(url('/api/db/disconnect'), {
    method: 'POST',
    credentials: 'include',
  });
  return response.json() as Promise<DbConnectResult>;
}

export async function getDbConnectionStatus(): Promise<DbStatusResult> {
  const response = await fetch(url('/api/db/status'), {
    credentials: 'include',
  });
  return response.json() as Promise<DbStatusResult>;
}

// ---------------------------------------------------------------- saved charts / dashboard

export type ChartRecipe = {
  title?: string;
  sql: string;
  mark: string;
  encoding: unknown;
  transform?: unknown;
  layout?: string | null;
};

/** A chart re-rendered live by the dashboard. `spec` is a Vega-Lite JSON string; on SQL
 *  failure (e.g. the schema changed) `error` is set instead. */
export type DashboardChart = {
  id: string;
  title: string;
  layout?: string | null;
  sql?: string;
  spec?: string;
  error?: string;
};

/** Save a chart into a project's dashboard (the SQL must be a read-only SELECT). */
export async function saveChart(
  projectId: string,
  recipe: ChartRecipe,
): Promise<{ success: boolean; chart?: unknown; detail?: string }> {
  const response = await fetch(url(`/api/projects/${encodeURIComponent(projectId)}/charts`), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(recipe),
  });
  return response.json();
}

/** Re-run every saved chart in the project → fresh Vega-Lite specs (live data). */
export async function renderDashboard(
  projectId: string,
): Promise<{ success: boolean; charts: DashboardChart[] }> {
  const response = await fetch(url(`/api/projects/${encodeURIComponent(projectId)}/dashboard/render`), {
    credentials: 'include',
  });
  return response.json();
}

export async function deleteSavedChart(chartId: string): Promise<{ success: boolean }> {
  const response = await fetch(url(`/api/charts/${encodeURIComponent(chartId)}`), {
    method: 'DELETE',
    credentials: 'include',
  });
  return response.json();
}

/** Edit a saved chart's title / SQL / layout (SQL re-verified read-only server-side). */
export async function updateChart(
  chartId: string,
  body: { title?: string; sql?: string; layout?: string | null },
): Promise<{ success: boolean; detail?: string }> {
  const response = await fetch(url(`/api/charts/${encodeURIComponent(chartId)}`), {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return response.json();
}

/** Persist a new chart order for a project's dashboard. */
export async function reorderDashboard(
  projectId: string,
  chartIds: string[],
): Promise<{ success: boolean }> {
  const response = await fetch(url(`/api/projects/${encodeURIComponent(projectId)}/dashboard/reorder`), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chart_ids: chartIds }),
  });
  return response.json();
}
