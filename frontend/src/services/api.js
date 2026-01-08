// Sử dụng proxy trong development, hoặc VITE_API_URL nếu có
// Default port 5001 để tránh conflict với AirPlay trên macOS
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5001';

/**
 * Gửi message đến backend và nhận response
 */
export const sendMessage = async (message, sessionId = null) => {
  try {
    const url = API_BASE_URL.startsWith('http') ? `${API_BASE_URL}/api/chat` : `/api/chat`;
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message,
        session_id: sessionId,
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Failed to send message');
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error sending message:', error);
    throw error;
  }
};

/**
 * Lấy danh sách sessions
 */
export const getSessions = async () => {
  try {
    const url = API_BASE_URL.startsWith('http') ? `${API_BASE_URL}/api/sessions` : `/api/sessions`;
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error('Failed to get sessions');
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error getting sessions:', error);
    throw error;
  }
};

/**
 * Tạo session mới
 */
export const createSession = async (name = null) => {
  try {
    const url = API_BASE_URL.startsWith('http') ? `${API_BASE_URL}/api/sessions/new` : `/api/sessions/new`;
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        name,
      }),
    });

    if (!response.ok) {
      throw new Error('Failed to create session');
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error creating session:', error);
    throw error;
  }
};

/**
 * Lấy thông tin session
 */
export const getSession = async (sessionId) => {
  try {
    const url = API_BASE_URL.startsWith('http') ? `${API_BASE_URL}/api/sessions/${sessionId}` : `/api/sessions/${sessionId}`;
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error('Failed to get session');
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error getting session:', error);
    throw error;
  }
};

/**
 * Health check
 */
export const healthCheck = async () => {
  try {
    const url = API_BASE_URL.startsWith('http') ? `${API_BASE_URL}/api/health` : `/api/health`;
    const response = await fetch(url, {
      method: 'GET',
    });

    if (!response.ok) {
      throw new Error('Health check failed');
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error health check:', error);
    throw error;
  }
};

