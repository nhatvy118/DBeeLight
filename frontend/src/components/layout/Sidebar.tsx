import { useEffect, useState } from 'react';
import { createSession, getSessions, createProject, getProjects, type SessionInfo } from '../../services/api';
import ProjectModal from '../modals/ProjectModal';
import DatabaseConnectPopup, { type DatabaseConnectionData } from '../modals/DatabaseConnectPopup';
import settingsIcon from '../../assets/icons/Settings.svg';
import gridIcon from '../../assets/icons/Grid.svg';
import penIcon from '../../assets/icons/Pen.svg';
import databaseIcon from '../../assets/icons/Database.svg';
import folderPlusIcon from '../../assets/icons/Folder plus.svg';
import folderIcon from '../../assets/icons/Folder.svg';
import userIcon from '../../assets/icons/User.svg';
import sidebarIcon from '../../assets/icons/Sidebar.svg';
import beeLogo from '../../assets/icons/bee.png';

type Project = {
  id: string;
  name: string;
  description?: string;
  createdAt: string;
};

type SidebarProps = {
  onSessionSelect?: (sessionId: string) => void;
  currentSessionId?: string | null;
};

export default function Sidebar({ onSessionSelect, currentSessionId }: SidebarProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [projects, setProjects] = useState<Project[]>([]);
  const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
  const [isDatabasePopupOpen, setIsDatabasePopupOpen] = useState(false);
  const [user, setUser] = useState<{ name?: string; email?: string; picture?: string } | null>(null);
  const [isCollapsed, setIsCollapsed] = useState<boolean>(false);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  // Load user info
  useEffect(() => {
    const loadUser = async () => {
      try {
        const res = await fetch('/api/auth/me', { method: 'GET', credentials: 'include' });
        const data = (await res.json()) as { authenticated: boolean; user?: { name?: string; email?: string; picture?: string } | null };
        setUser(data.authenticated ? (data.user ?? null) : null);
      } catch {
        setUser(null);
      }
    };
    void loadUser();
  }, []);

  // Sync selectedProjectId with URL - URL is source of truth
  useEffect(() => {
    const updateFromURL = () => {
      const path = window.location.pathname;
      const parts = path.split('/').filter(Boolean);
      if (parts.length >= 2 && parts[0] === 'chat') {
        const id = parts[1];
        // Check if it's a project ID (UUID format) or session ID (short format)
        if (id.includes('-') && id.length > 20) {
          // Likely a project ID (UUID)
          setSelectedProjectId(id);
          return;
        }
      }
      // No project in URL
      setSelectedProjectId(null);
    };

    updateFromURL();
    window.addEventListener('popstate', updateFromURL);
    return () => window.removeEventListener('popstate', updateFromURL);
  }, []);

  // Fetch projects from API for the current user only (not from localStorage)
  useEffect(() => {
    if (!user) {
      setProjects([]);
      setSelectedProjectId(null);
      localStorage.removeItem('projects');
      return;
    }
    let cancelled = false;
    const loadProjects = async () => {
      try {
        const res = await getProjects();
        if (cancelled) return;
        if (res.success && res.projects) {
          const list: Project[] = res.projects.map((p) => ({
            id: p.id,
            name: p.name,
            description: p.description,
            createdAt: p.created_at ?? new Date().toISOString(),
          }));
          setProjects(list);
          localStorage.setItem('projects', JSON.stringify(list));
          // Don't set selectedProjectId from localStorage - URL is source of truth
          // selectedProjectId will be set from URL via AppRoutes
        } else {
          setProjects([]);
        }
      } catch {
        if (!cancelled) setProjects([]);
      }
    };
    void loadProjects();
    return () => { cancelled = true; };
  }, [user]);

  const fetchSessions = async () => {
    try {
      setIsLoading(true);
      // Only fetch unassigned sessions (sessions where project_id IS NULL)
      const res = await getSessions(null, true);
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
  }, []);

  // Listen for changes in projectSessions to update the display
  useEffect(() => {
    const handleStorageChange = () => {
      // Force re-render by fetching sessions again
      void fetchSessions();
    };

    window.addEventListener('storage', handleStorageChange);
    window.addEventListener('projectSessionsUpdated', handleStorageChange);

    return () => {
      window.removeEventListener('storage', handleStorageChange);
      window.removeEventListener('projectSessionsUpdated', handleStorageChange);
    };
  }, []);

  const handleNewChat = async () => {
    try {
      // Create new session without project (unassigned)
      const res = await createSession(null, null);
      if (res.success && res.session_id) {
        // Clear selected project state
        setSelectedProjectId(null);

        await fetchSessions(); // Refresh list
        // Navigate to /chat/sessionId for unassigned session (URL is source of truth)
        navigate(`/chat/${res.session_id}`);
        if (onSessionSelect) {
          onSessionSelect(res.session_id);
        }
      }
    } catch (err) {
      console.error('Failed to create session:', err);
      window.alert('Failed to create new chat');
    }
  };

  // Sessions are already filtered to only include unassigned ones from API
  // This function is kept for consistency but just returns all sessions
  const getUnassignedSessions = (): SessionInfo[] => {
    // All sessions in state are already unassigned (fetched with unassigned_only=true)
    return sessions;
  };

  const handleSessionClick = (sessionId: string) => {
    // Find the session to check if it has a project_id
    const session = sessions.find(s => s.session_id === sessionId);

    // Navigate based on session type (URL is source of truth)
    if (session && !session.project_id) {
      // Unassigned session
      setSelectedProjectId(null);
      navigate(`/chat/${sessionId}`);
    } else if (session && session.project_id) {
      // Project session
      setSelectedProjectId(session.project_id);
      navigate(`/chat/${session.project_id}/${sessionId}`);
    } else {
      // Fallback: navigate to /chat/sessionId
      navigate(`/chat/${sessionId}`);
    }

    if (onSessionSelect) {
      onSessionSelect(sessionId);
    }
  };

  const formatSessionName = (session: SessionInfo): string => {
    if (session.session_name && session.session_name.trim()) {
      return session.session_name;
    }
    return 'New chat';
  };

  const handleCreateProject = async (name: string, description?: string) => {
    try {
      const res = await createProject(name, description);
      if (res.success && res.project) {
        // Refetch projects from API so list stays per-user
        const listRes = await getProjects();
        if (listRes.success && listRes.projects) {
          const projectList: Project[] = listRes.projects.map((p) => ({
            id: p.id,
            name: p.name,
            description: p.description,
            createdAt: p.created_at ?? new Date().toISOString(),
          }));
          setProjects(projectList);
          localStorage.setItem('projects', JSON.stringify(projectList));
        }
      } else {
        console.error('Failed to create project:', res);
        window.alert('Failed to create project');
      }
    } catch (err) {
      console.error('Failed to create project:', err);
      window.alert('Failed to create project');
    }
  };

  const handleDatabaseConnect = (connectionData: DatabaseConnectionData) => {
    console.log('Connecting to database with:', connectionData);
    // TODO: Implement actual database connection logic
    // For now, just close the popup and show success message
    alert(`Connecting to ${connectionData.databaseName} at ${connectionData.server}:${connectionData.port}`);
    setIsDatabasePopupOpen(false);
  };

  const navigate = (path: string) => {
    window.history.pushState({}, '', path);
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  return (
    <>
      <div
        className={`h-screen flex flex-col relative transition-all duration-300 ${isCollapsed ? '' : 'border-r-2 border-gray-300'}`}
        style={{
          backgroundColor: '#F9F9FA',
          flex: isCollapsed ? '0 0 auto' : '1 1 15%',
          width: isCollapsed ? '80px' : undefined,
          minWidth: isCollapsed ? '80px' : '200px'
        }}
      >
        {/* Main Content Area - Flex container for proportional sections */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Logo Section - Smaller */}
          <div className="p-4 border-b-2 border-gray-300 relative group flex-shrink-0" style={{ flex: '0 0 auto', minHeight: '60px' }}>
            <div className={`flex items-center ${isCollapsed ? 'justify-center' : 'gap-2'}`}>
              <img
                src={beeLogo}
                alt="LightDBee"
                className={`w-8 h-8 transition-opacity ${isCollapsed ? 'group-hover:opacity-0' : ''}`}
              />
              {!isCollapsed && (
                <span className="text-xl font-semibold text-gray-900">LightDBee</span>
              )}
            </div>
            {/* Sidebar Icon - Show on hover when collapsed */}
            {isCollapsed && (
              <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={() => setIsCollapsed(!isCollapsed)}
                  className="text-gray-600 hover:text-gray-900 transition-colors"
                  type="button"
                >
                  <img src={sidebarIcon} alt="Sidebar" className="w-10 h-10" />
                </button>
              </div>
            )}
            {/* Sidebar Icon - Always visible when expanded */}
            {!isCollapsed && (
              <div className="absolute top-4 right-4 z-10">
                <button
                  onClick={() => setIsCollapsed(!isCollapsed)}
                  className="text-gray-600 hover:text-gray-900 transition-colors"
                  type="button"
                >
                  <img src={sidebarIcon} alt="Sidebar" className="w-10 h-10" />
                </button>
              </div>
            )}
          </div>

          {/* Top Section - Smaller */}
          <div className="p-4 flex-shrink-0 overflow-y-auto" style={{ flex: '0 0 auto' }}>
            {/* Navigation Items */}
            <div className="space-y-0.5">
              <button
                onClick={handleNewChat}
                className={`w-full flex items-center ${isCollapsed ? 'justify-center px-2' : 'gap-3 px-3'} py-1.5 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors text-left`}
                type="button"
                title={isCollapsed ? 'New chat' : undefined}
              >
                <img src={penIcon} alt="New chat" className="w-6 h-6" />
                {!isCollapsed && <span className="text-base font-medium">New chat</span>}
              </button>

              <button
                onClick={() => setIsDatabasePopupOpen(true)}
                className={`w-full flex items-center ${isCollapsed ? 'justify-center px-2' : 'gap-3 px-3'} py-1.5 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors text-left`}
                type="button"
                title={isCollapsed ? 'Connect Database' : undefined}
              >
                <img src={databaseIcon} alt="Connect Database" className="w-6 h-6" />
                {!isCollapsed && <span className="text-base font-medium">Connect Database</span>}
              </button>

              <button
                onClick={() => setIsProjectModalOpen(true)}
                className={`w-full flex items-center ${isCollapsed ? 'justify-center px-2' : 'gap-3 px-3'} py-1.5 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors text-left`}
                type="button"
                title={isCollapsed ? 'Add Project' : undefined}
              >
                <img src={folderPlusIcon} alt="Add Project" className="w-6 h-6" />
                {!isCollapsed && <span className="text-base font-medium">Add Project</span>}
              </button>
            </div>
          </div>

          {/* Projects Section - 3 parts */}
          {!isCollapsed && (
            <div className="border-t border-gray-200 flex-shrink-0 flex flex-col overflow-hidden" style={{ flex: '3 1 0' }}>
              <div className="px-4 py-3 flex-shrink-0">
                <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">Projects</h2>
              </div>
              <div className="flex-1 overflow-y-auto px-4 pb-3">
                {projects.length === 0 ? (
                  <div className="text-sm text-gray-400 italic">No projects yet</div>
                ) : (
                  <div className="space-y-1">
                    {projects.map((project) => (
                      <button
                        key={project.id}
                        onClick={() => {
                          setSelectedProjectId(project.id);
                          // Navigate to project view (no session) - URL is source of truth
                          navigate(`/chat/${project.id}`);
                          // Clear selected session when switching projects
                          if (onSessionSelect) {
                            onSessionSelect(null as any);
                          }
                        }}
                        className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors text-left ${selectedProjectId === project.id ? 'bg-gray-100 font-semibold' : ''}`}
                        type="button"
                      >
                        <img src={folderIcon} alt="Folder" className="w-5 h-5 flex-shrink-0" />
                        <span className="text-sm font-medium truncate">{project.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Chats Section - 3 parts */}
          {!isCollapsed && (
            <div className="border-t border-gray-200 flex-shrink-0 flex flex-col overflow-hidden" style={{ flex: '3 1 0' }}>
              <div className="px-4 py-3 flex-shrink-0">
                <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">Chat History</h2>
              </div>
              <div className="flex-1 overflow-y-auto px-4 pb-3">
                {isLoading ? (
                  <div className="text-sm text-gray-500">Loading...</div>
                ) : getUnassignedSessions().length === 0 ? (
                  <div className="text-sm text-gray-400 italic">No unassigned chats yet</div>
                ) : (
                  <div className="space-y-1">
                    {getUnassignedSessions().map((session) => (
                      <button
                        key={session.session_id}
                        onClick={() => handleSessionClick(session.session_id)}
                        className={`w-full text-left px-3 py-2.5 rounded-lg transition-colors text-sm ${currentSessionId === session.session_id
                          ? 'bg-gray-100 text-gray-900 font-medium'
                          : 'hover:bg-gray-50 text-gray-700'
                          }`}
                        type="button"
                      >
                        <span className="truncate block">{formatSessionName(session)}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Bottom Profile - Always at bottom */}
        <div className={`mt-auto p-5`}>
          <div className={`flex items-center ${isCollapsed ? 'justify-center' : 'gap-3'}`}>
            {user?.picture ? (
              <img
                src={user.picture}
                alt={user.name || user.email || 'User'}
                className="w-10 h-10 rounded-full"
                referrerPolicy="no-referrer"
              />
            ) : (
              <img src={userIcon} alt="User" className="w-10 h-10" />
            )}
            {!isCollapsed && (
              <span className="text-base font-medium text-gray-900 truncate">
                {user?.name || user?.email || 'User'}
              </span>
            )}
          </div>
        </div>
      </div>

      <ProjectModal
        isOpen={isProjectModalOpen}
        onClose={() => setIsProjectModalOpen(false)}
        onCreate={handleCreateProject}
      />

      <DatabaseConnectPopup
        isOpen={isDatabasePopupOpen}
        onClose={() => setIsDatabasePopupOpen(false)}
        onConnect={handleDatabaseConnect}
      />
    </>
  );
}

