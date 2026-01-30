import React, { useEffect, useMemo, useRef, useState } from 'react';
import MessageList, { type UiMessage } from '../components/chat/MessageList';
import { getSession, sendMessage, getSessions, type SessionInfo } from '../services/api';
import plusIcon from '../assets/icons/Plus.svg';
import microphoneIcon from '../assets/icons/Microphone.svg';
import arrowUpCircleIcon from '../assets/icons/Arrow-up-circle.svg';
import helpIcon from '../assets/icons/Help.svg';

const MAX_TEXTAREA_HEIGHT = 200;
const MIN_TEXTAREA_HEIGHT = 60;

type ChatProps = {
  sessionId?: string | null;
  onSessionIdChange?: (sessionId: string | null) => void;
};

export default function Chat({ sessionId: propSessionId, onSessionIdChange }: ChatProps) {
  const [query, setQuery] = useState<string>('');
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [sessionId, setSessionId] = useState<string | null>(propSessionId || null);
  const [selectedProject, setSelectedProject] = useState<{ id: string; name: string } | null>(null);
  const [projectSessions, setProjectSessions] = useState<SessionInfo[]>([]);
  const [sessionPreviews, setSessionPreviews] = useState<Record<string, string>>({});
  const previousProjectIdRef = useRef<string | null>(null);

  // Load and update selected project from localStorage
  const loadSelectedProject = () => {
    const selectedProjectId = localStorage.getItem('selectedProjectId');

    // Check if project changed
    if (selectedProjectId !== previousProjectIdRef.current) {
      console.log('🔄 PROJECT CHANGED! Clearing session and messages');
      setSessionId(null);
      setMessages([]);
      onSessionIdChange?.(null);
      previousProjectIdRef.current = selectedProjectId;
    }

    if (selectedProjectId) {
      const projects = JSON.parse(localStorage.getItem('projects') || '[]');
      const project = projects.find((p: { id: string }) => p.id === selectedProjectId);
      if (project) {
        console.log('Project found:', project.name);
        setSelectedProject({ id: project.id, name: project.name });
      } else {
        console.log('Project not found, clearing');
        setSelectedProject(null);
      }
    } else {
      console.log('No project selected');
      setSelectedProject(null);
    }
  };

  useEffect(() => {
    loadSelectedProject();
    // Initialize the previousProjectIdRef with current project
    const currentProjectId = localStorage.getItem('selectedProjectId');
    previousProjectIdRef.current = currentProjectId;
  }, []);

  // Listen for project selection changes
  useEffect(() => {
    const handleProjectSelected = () => {
      console.log('📢 Received projectSelected event');
      loadSelectedProject();
    };

    // Listen to custom event for same-tab updates
    window.addEventListener('projectSelected', handleProjectSelected);

    // Also poll localStorage periodically to catch changes
    const interval = setInterval(() => {
      loadSelectedProject();
    }, 500);

    return () => {
      window.removeEventListener('projectSelected', handleProjectSelected);
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const canSend = useMemo(() => !isLoading && query.trim().length > 0, [isLoading, query]);

  // Load session when sessionId prop changes
  useEffect(() => {
    const loadSession = async (sid: string) => {
      try {
        setIsLoading(true);
        const res = await getSession(sid);
        if (res.success && res.messages) {
          const convertedMessages: UiMessage[] = res.messages
            .filter((msg: any) => msg.role === 'user' || msg.role === 'assistant')
            .map((msg: any) => ({
              text: msg.content || '',
              isUser: msg.role === 'user',
            }));
          setMessages(convertedMessages);
          setSessionId(sid);
          onSessionIdChange?.(sid);
        }
      } catch (err) {
        console.error('Failed to load session:', err);
        window.alert('Failed to load chat history');
      } finally {
        setIsLoading(false);
      }
    };

    if (propSessionId && propSessionId !== sessionId) {
      void loadSession(propSessionId);
    } else if (!propSessionId && sessionId) {
      console.log('Clearing session: switching to new project or new chat');
      setMessages([]);
      setSessionId(null);
      onSessionIdChange?.(null);
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
    console.log('Sending message with sessionId:', sessionId);
    console.log('Selected project:', selectedProject);
    try {
      const res = await sendMessage(text, sessionId, selectedProject?.id || null);
      if (res.success) {
        setMessages((prev) => [...prev, { text: res.response, isUser: false }]);
        if (res.session_id) {
          const newSessionId = res.session_id;
          const isNewSession = sessionId !== newSessionId;
          console.log('Response sessionId:', newSessionId, 'isNewSession:', isNewSession);

          setSessionId(newSessionId);
          onSessionIdChange?.(newSessionId);

          // Reload project sessions to update the history UI
          if (isNewSession) {
            setTimeout(() => {
              void loadProjectSessions();
            }, 500);
          }
        }
      } else {
        setMessages((prev) => [...prev, { text: `Error: ${res.error || 'Failed to get response'}`, isUser: false }]);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to connect to server';
      setMessages((prev) => [...prev, { text: `Error: ${message}`, isUser: false }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = async () => {
    const text = query.trim();
    if (!text || isLoading) return;

    setMessages((prev) => [...prev, { text, isUser: true }]);
    setQuery('');
    await doSend(text);
  };

  const handleRefreshResponse = async (aiIndex: number) => {
    const userIndex = aiIndex - 1;
    if (userIndex < 0) return;
    const userMsg = messages[userIndex];
    if (!userMsg?.isUser) return;

    setIsLoading(true);
    try {
      const res = await sendMessage(userMsg.text, sessionId, selectedProject?.id || null);
      if (res.success) {
        setMessages((prev) => {
          const updated = [...prev];
          updated[aiIndex] = { text: res.response, isUser: false };
          return updated;
        });
      } else {
        window.alert(`Error: ${res.error || 'Failed to refresh response'}`);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to refresh response';
      window.alert(`Error: ${message}`);
    } finally {
      setIsLoading(false);
    }
  };

  // Clear session when selectedProject changes
  useEffect(() => {
    setSessionId(null);
    setMessages([]);
    onSessionIdChange?.(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProject?.id]);

  // Function to load project sessions
  const loadProjectSessions = async () => {
    if (!selectedProject) {
      console.log('No selected project, clearing project sessions');
      setProjectSessions([]);
      setSessionPreviews({});
      return;
    }

    console.log('Loading sessions for project:', selectedProject.name, selectedProject.id);
    try {
      // Get sessions filtered by project_id from backend
      const res = await getSessions(selectedProject.id);
      if (res.success) {
        console.log('Sessions from API for this project:', res.sessions.length);
        setProjectSessions(res.sessions);

        // Load preview for each session (first user message)
        const previews: Record<string, string> = {};
        for (const session of res.sessions) {
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

  // Load project sessions when project is selected
  useEffect(() => {
    void loadProjectSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProject]);

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

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Chat Content */}
      {messages.length > 0 && (
        <div className="flex-1 overflow-y-auto px-8 py-6">
          <div className="max-w-4xl mx-auto">
            <MessageList messages={messages} onRefreshResponse={(idx) => void handleRefreshResponse(idx)} />
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
              <h2 className="text-5xl md:text-6xl font-bold text-gray-900">Hi, How are you today?</h2>
            </div>
          )}
          <div className="relative bg-white border-2 border-gray-300 rounded-3xl px-4 shadow-lg">
            <div className="flex items-center gap-3 min-h-[48px]">
              <button
                type="button"
                className="text-gray-500 hover:text-gray-700 flex-shrink-0"
              >
                <img src={plusIcon} alt="Add" className="w-5 h-5" />
              </button>

              <textarea
                ref={textareaRef}
                value={query}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                  setQuery(e.target.value)
                }
                onKeyDown={(e: React.KeyboardEvent<HTMLTextAreaElement>) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void handleSend();
                  }
                }}
                placeholder={
                  selectedProject
                    ? `New chat in ${selectedProject.name}`
                    : "Ask anything"
                }
                rows={1}
                className="flex-1 resize-none outline-none text-lg"
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
                  onClick={(): void => { void handleSend(); }}
                  disabled={!canSend}
                  className="flex items-center justify-center w-10 h-10 rounded-full p-0 opacity-60 hover:opacity-100 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
                  aria-label="Send"
                >
                  <img src={arrowUpCircleIcon} alt="" className="w-20 h-20" />
                </button>
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
              <p className="text-center text-xs text-gray-500">
              By using LightDBee, you agree to our Term and Service Policy
              </p>
            </div>
          </div>
        )
      }

    </div >
  );
}

