import { useEffect, useState } from 'react';
import { getSessions, createSession, SessionInfo } from '../services/api';

type NavItem = { icon: string; label: string };

type SidebarProps = {
  onSessionSelect?: (sessionId: string) => void;
  currentSessionId?: string | null;
};

export default function Sidebar({ onSessionSelect, currentSessionId }: SidebarProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const navItems: NavItem[] = [
    { icon: '?', label: 'Help' },
    { icon: '✓', label: 'Activity' },
    { icon: '⚙', label: 'Settings' },
    { icon: '!', label: 'Account Info' },
  ];

  const fetchSessions = async () => {
    try {
      setIsLoading(true);
      const res = await getSessions();
      if (res.success) {
        setSessions(res.sessions || []);
      }
    } catch (err) {
      console.error('Failed to fetch sessions:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void fetchSessions();
    // Refresh sessions every 5 seconds
    const interval = setInterval(() => {
      void fetchSessions();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleNewChat = async () => {
    try {
      const res = await createSession();
      if (res.success && res.session_id) {
        await fetchSessions(); // Refresh list
        if (onSessionSelect) {
          onSessionSelect(res.session_id);
        }
      }
    } catch (err) {
      console.error('Failed to create session:', err);
      window.alert('Failed to create new chat');
    }
  };

  const handleSessionClick = (sessionId: string) => {
    if (onSessionSelect) {
      onSessionSelect(sessionId);
    }
  };

  const formatSessionName = (session: SessionInfo): string => {
    if (session.session_name && session.session_name !== `Session ${session.session_id}`) {
      return session.session_name;
    }
    // Format date from created_at
    if (session.created_at) {
      try {
        const date = new Date(session.created_at);
        const timeStr = date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
        return `Chat ${timeStr}`;
      } catch {
        return `Chat ${session.session_id.slice(0, 8)}`;
      }
    }
    return `Chat ${session.session_id.slice(0, 8)}`;
  };

  return (
    <div className="w-64 bg-white h-screen flex flex-col shadow-sm">
      {/* Hamburger Menu */}
      <div className="p-4">
        <button className="text-gray-700 hover:text-gray-900" type="button">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 6h16M4 12h16M4 18h16"
            />
          </svg>
        </button>
      </div>

      {/* New Chat Button */}
      <div className="px-4 mb-6">
        <button
          onClick={handleNewChat}
          className="w-full bg-blue-500 hover:bg-blue-600 text-white font-semibold py-3 px-4 rounded-lg transition-colors"
          type="button"
        >
          + New Chat
        </button>
      </div>

      {/* Chats History */}
      <div className="px-4 mb-6 flex-1 overflow-y-auto">
        <h2 className="text-lg font-bold text-gray-800 mb-3">Chats History</h2>
        {isLoading ? (
          <div className="text-sm text-gray-500">Loading sessions...</div>
        ) : sessions.length === 0 ? (
          <div className="text-sm text-gray-500">No chat history yet</div>
        ) : (
          <div className="space-y-2">
            {sessions.map((session) => (
              <button
                key={session.session_id}
                onClick={() => handleSessionClick(session.session_id)}
                className={`w-full text-left px-3 py-2 rounded-lg transition-colors ${
                  currentSessionId === session.session_id
                    ? 'bg-blue-100 text-blue-700 font-medium'
                    : 'hover:bg-gray-100 text-gray-700'
                }`}
                type="button"
              >
                <div className="flex flex-col">
                  <span className="text-sm truncate">{formatSessionName(session)}</span>
                  {session.message_count !== undefined && session.message_count > 0 && (
                    <span className="text-xs text-gray-500 mt-0.5">
                      {session.message_count} message{session.message_count !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Navigation Links */}
      <div className="mt-auto px-4 pb-6 space-y-2">
        {navItems.map((item, index) => (
          <button
            // eslint-disable-next-line react/no-array-index-key
            key={index}
            className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors"
            type="button"
          >
            <span className="text-lg">{item.icon}</span>
            <span className="font-medium">{item.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}


