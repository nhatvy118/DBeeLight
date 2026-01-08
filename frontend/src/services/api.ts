// Default port 5001 để tránh conflict với AirPlay trên macOS
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5001';

export type ChatResponse =
  | { success: true; response: string; session_id?: string | null }
  | { success: false; error: string };

export type SessionInfo = {
  session_id: string;
  session_name?: string;
  created_at?: string;
  message_count?: number;
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

export async function sendMessage(message: string, sessionId: string | null = null): Promise<ChatResponse> {
  const response = await fetch(url('/api/chat'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  });

  const data = (await response.json()) as ChatResponse & { error?: string };
  if (!response.ok) {
    throw new Error((data as any).error || 'Failed to send message');
  }
  return data;
}

export async function getSessions(): Promise<SessionsResponse> {
  const response = await fetch(url('/api/sessions'), { method: 'GET', headers: { 'Content-Type': 'application/json' } });
  if (!response.ok) throw new Error('Failed to get sessions');
  return (await response.json()) as SessionsResponse;
}

export async function createSession(name: string | null = null): Promise<CreateSessionResponse> {
  const response = await fetch(url('/api/sessions/new'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) throw new Error('Failed to create session');
  return (await response.json()) as CreateSessionResponse;
}

export async function getSession(sessionId: string): Promise<GetSessionResponse> {
  const response = await fetch(url(`/api/sessions/${encodeURIComponent(sessionId)}`), {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) throw new Error('Failed to get session');
  return (await response.json()) as GetSessionResponse;
}

export async function healthCheck(): Promise<HealthResponse> {
  const response = await fetch(url('/api/health'), { method: 'GET' });
  if (!response.ok) throw new Error('Health check failed');
  return (await response.json()) as HealthResponse;
}


