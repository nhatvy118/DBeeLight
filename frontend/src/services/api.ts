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

export type ProjectKind = 'internal' | 'external';

export type ProjectItem = {
  id: string;
  name: string;
  description?: string;
  created_at?: string;
  kind?: ProjectKind;
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
  | { success: true; project: { id: string; name: string; description?: string; created_at?: string; kind?: ProjectKind } }
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

/** Fetch a single project (owner OR shared-with). Used when it isn't in the local cache,
 * e.g. a viewer opening a project shared with them. */
export async function getProject(id: string): Promise<{ id: string; name: string; description: string }> {
  const res = await fetch(url(`/api/projects/${encodeURIComponent(id)}`), { credentials: 'include' });
  if (!res.ok) throw new Error('Project not found');
  return (await res.json()) as { id: string; name: string; description: string };
}

// ----- Project sharing (viewer access) -----

export type SharedProject = {
  id: string;
  name: string;
  description: string;
  owner_name: string | null;
  owner_email: string | null;
  shared_at: string | null;
};

export type SharePermission = 'view' | 'edit';

export type ProjectShare = {
  user_id: string;
  name: string | null;
  email: string | null;
  role: AdminRole;
  permission: SharePermission;
  shared_at: string | null;
};

/** Projects shared WITH the current user (the viewer home). */
export async function listSharedProjects(): Promise<SharedProject[]> {
  const res = await fetch(url('/api/projects/shared/with-me'), { credentials: 'include' });
  const data = await _adminJson<{ projects: SharedProject[] }>(res, 'Failed to load shared projects');
  return data.projects ?? [];
}

export type ShareableUser = { user_id: string; name: string | null; email: string | null; role: AdminRole };

/** Users this project can still be shared with (pick-list, excludes owner + already-shared). */
export async function listShareableUsers(projectId: string): Promise<ShareableUser[]> {
  const res = await fetch(url(`/api/projects/${encodeURIComponent(projectId)}/shareable`), { credentials: 'include' });
  const data = await _adminJson<{ users: ShareableUser[] }>(res, 'Failed to load users');
  return data.users ?? [];
}

/** People a project is shared with (owner view). */
export async function listProjectShares(projectId: string): Promise<ProjectShare[]> {
  const res = await fetch(url(`/api/projects/${encodeURIComponent(projectId)}/shares`), { credentials: 'include' });
  const data = await _adminJson<{ shares: ProjectShare[] }>(res, 'Failed to load shares');
  return data.shares ?? [];
}

export async function shareProject(projectId: string, email: string, permission: SharePermission = 'view'): Promise<ProjectShare> {
  const res = await fetch(url(`/api/projects/${encodeURIComponent(projectId)}/shares`), {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, permission }),
  });
  return (await _adminJson<{ share: ProjectShare }>(res, 'Failed to share project')).share;
}

/** Change a person's access on a project. Returns the EFFECTIVE permission (viewers stay 'view'). */
export async function setSharePermission(projectId: string, viewerId: string, permission: SharePermission): Promise<SharePermission> {
  const res = await fetch(url(`/api/projects/${encodeURIComponent(projectId)}/shares/${encodeURIComponent(viewerId)}/permission`), {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ permission }),
  });
  return (await _adminJson<{ permission: SharePermission }>(res, 'Failed to update access')).permission;
}

export async function unshareProject(projectId: string, viewerId: string): Promise<void> {
  const res = await fetch(url(`/api/projects/${encodeURIComponent(projectId)}/shares/${encodeURIComponent(viewerId)}`), {
    method: 'DELETE', credentials: 'include',
  });
  await _adminJson<unknown>(res, 'Failed to remove access');
}

// ----- Admin: people & roles -----

export type AdminRole = 'admin' | 'technical' | 'viewer';

export type AdminUser = {
  id: number;
  name: string | null;
  email: string | null;
  role: AdminRole;
  status: 'active' | 'disabled';
  created_at: string | null;
  project_count: number;
  session_count: number;
  storage_bytes: number;
  is_self: boolean;
};

export type AdminInvite = {
  id: number;
  email: string;
  role: AdminRole;
  status: 'pending';
  created_at: string | null;
};

export type AdminStats = {
  total_users: number;
  disabled_users: number;
  admin_users: number;
  technical_users: number;
  viewer_users: number;
  pending_invites: number;
  total_projects: number;
  total_sessions: number;
  total_storage_bytes: number;
};

export type AdminOverview = { stats: AdminStats; users: AdminUser[]; invites: AdminInvite[] };

async function _adminJson<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const d = (await res.json().catch(() => ({}))) as { detail?: string; error?: string };
    throw new Error(d.detail || d.error || fallback);
  }
  return (await res.json()) as T;
}

export async function getAdminOverview(): Promise<AdminOverview> {
  const res = await fetch(url('/api/admin/overview'), { credentials: 'include' });
  const data = await _adminJson<{ stats: AdminStats; users: AdminUser[]; invites: AdminInvite[] }>(res, 'Failed to load admin data');
  return { stats: data.stats, users: data.users ?? [], invites: data.invites ?? [] };
}

export async function adminInvite(email: string, role: AdminRole): Promise<AdminInvite> {
  const res = await fetch(url('/api/admin/invite'), {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, role }),
  });
  return (await _adminJson<{ invite: AdminInvite }>(res, 'Failed to send invite')).invite;
}

export async function adminRevokeInvite(inviteId: number): Promise<void> {
  const res = await fetch(url(`/api/admin/invite/${inviteId}`), { method: 'DELETE', credentials: 'include' });
  await _adminJson<unknown>(res, 'Failed to revoke invite');
}

export async function adminSetInviteRole(inviteId: number, role: AdminRole): Promise<void> {
  const res = await fetch(url(`/api/admin/invite/${inviteId}/role`), {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  });
  await _adminJson<unknown>(res, 'Failed to update invite');
}

export async function adminSetUserRole(userId: number, role: AdminRole): Promise<void> {
  const res = await fetch(url(`/api/admin/users/${userId}/role`), {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  });
  await _adminJson<unknown>(res, 'Failed to change role');
}

/** Disable (lock out) or re-enable a user account. Returns the new disabled state. */
export async function setUserDisabled(userId: number, disabled: boolean): Promise<boolean> {
  const action = disabled ? 'disable' : 'enable';
  const res = await fetch(url(`/api/admin/users/${userId}/${action}`), {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  });
  return (await _adminJson<{ disabled: boolean }>(res, 'Failed to update user')).disabled;
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

/** Connection form for an external Postgres database (project-bound). */
export type ExternalConnectionInput = {
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
};

/** Probe a connection without creating anything (the "Test connection" button). */
export async function testExternalConnection(conn: ExternalConnectionInput): Promise<DbConnectResult> {
  const response = await fetch(url('/api/projects/external/test'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(conn),
  });
  return response.json() as Promise<DbConnectResult>;
}

/** Create a project bound to the user's own external Postgres database. */
export async function createExternalProject(
  name: string, conn: ExternalConnectionInput, description?: string,
): Promise<CreateProjectResponse> {
  const response = await fetch(url('/api/projects/external'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ name, description, ...conn }),
  });
  if (!response.ok) {
    const data = (await response.json().catch(() => ({}))) as { detail?: string; error?: string };
    throw new Error(data.detail || data.error || 'Failed to create external project');
  }
  return (await response.json()) as CreateProjectResponse;
}

/** Re-point an external project at a new DSN (Edit connection). Owner-only. */
export async function updateProjectConnection(id: string, conn: ExternalConnectionInput): Promise<DbConnectResult> {
  const response = await fetch(url(`/api/projects/${encodeURIComponent(id)}/connection`), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(conn),
  });
  if (!response.ok) {
    const data = (await response.json().catch(() => ({}))) as { detail?: string };
    return { success: false, message: data.detail || 'Failed to update connection' };
  }
  return (await response.json()) as DbConnectResult;
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
