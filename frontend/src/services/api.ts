// Prefer relative "/api/*" so Vite proxy can handle same-origin cookies.
// You can override with VITE_API_URL if you don't want to use the proxy.
const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export type ChatResponse =
  | { success: true; response: string; session_id?: string | null }
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

export async function sendMessage(message: string, sessionId: string | null = null, projectId: string | null = null): Promise<ChatResponse> {
  const response = await fetch(url('/api/chat'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, project_id: projectId }),
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


