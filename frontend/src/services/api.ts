// Prefer relative "/api/*" so Vite proxy can handle same-origin cookies.
// You can override with VITE_API_URL if you don't want to use the proxy.
const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export type ToolEvent = {
  tool: string;
  type: string;
  payload?: Record<string, unknown>;
};

export type ChatResponse =
  | { success: true; response: string; session_id?: string | null; tool_events?: ToolEvent[] }
  | { success: false; error: string };

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

export type GetSessionResponse =
  | { success: true; session_info: unknown; messages: unknown[] }
  | { success: false; error: string };

export type HealthResponse = { status: 'ok'; agent_initialized: boolean };

function url(path: string) {
  return API_BASE_URL.startsWith('http') ? `${API_BASE_URL}${path}` : path;
}

export async function sendMessage(
  message: string,
  sessionId: string | null = null,
  projectId: string | null = null,
  signal?: AbortSignal
): Promise<ChatResponse> {
  const response = await fetch(url('/api/chat'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, project_id: projectId }),
    signal,
  });

  const data = (await response.json()) as ChatResponse & { error?: string };
  if (!response.ok) {
    throw new Error((data as any).error || 'Failed to send message');
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

export async function createSession(name: string | null = null, projectId: string | null = null): Promise<CreateSessionResponse> {
  const response = await fetch(url('/api/sessions/new'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, project_id: projectId }),
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

export async function createProject(name: string, description?: string, db_url: string = ''): Promise<CreateProjectResponse> {
  const response = await fetch(url('/api/projects'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description, db_url }),
  });
  if (!response.ok) {
    const data = (await response.json()) as { error?: string };
    throw new Error(data.error || 'Failed to create project');
  }
  return (await response.json()) as CreateProjectResponse;
}

export type GenerateShareLinkResponse =
  | { success: true; share_token: string; share_url: string }
  | { success: false; error: string };

export async function generateShareLink(sessionId: string | null = null, projectId: string | null = null): Promise<GenerateShareLinkResponse> {
  const response = await fetch(url('/api/share/generate'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, project_id: projectId }),
  });
  if (!response.ok) {
    const data = (await response.json()) as { error?: string };
    return { success: false, error: data.error || 'Failed to generate share link' };
  }
  return (await response.json()) as GenerateShareLinkResponse;
}

export type ExecuteSqlResponse = ChatResponse;

export async function executeSql(
  sql: string,
  actionId: string | null,
  sessionId: string | null = null,
  projectId: string | null = null,
  lang: string = 'en',
  lockOnly: boolean = false,
  lockState: 'executed' | 'cancelled' | null = null,
): Promise<ExecuteSqlResponse> {
  const response = await fetch(url('/api/sql/execute'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sql, action_id: actionId, session_id: sessionId, project_id: projectId, lang, lock_only: lockOnly, lock_state: lockState }),
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

export type UploadExcelResponse =
  | {
      success: true;
      file: {
        original_name: string;
        stored_name: string;
        server_path: string;
        size_bytes: number;
        session_id?: string | null;
        project_id?: string | null;
      };
    }
  | { success: false; error: string };

export async function uploadExcel(
  file: File,
  sessionId: string | null = null,
  projectId: string | null = null
): Promise<UploadExcelResponse> {
  const form = new FormData();
  form.append('file', file);
  if (sessionId) form.append('session_id', sessionId);
  if (projectId) form.append('project_id', projectId);

  const response = await fetch(url('/api/excel/upload'), {
    method: 'POST',
    credentials: 'include',
    body: form,
  });

  if (!response.ok) {
    let detail = 'Failed to upload file';
    try {
      const data = (await response.json()) as { detail?: string; error?: string };
      detail = data.detail || data.error || detail;
    } catch {
      // ignore JSON parse errors
    }
    return { success: false, error: detail };
  }
  return (await response.json()) as UploadExcelResponse;
}


