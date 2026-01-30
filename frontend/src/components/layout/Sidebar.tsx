import { useEffect, useState } from 'react';
import { createSession, getSessions, createProject, type SessionInfo } from '../../services/api';
import ProjectModal from '../modals/ProjectModal';
import DatabaseConnectPopup, { type DatabaseConnectionData } from '../modals/DatabaseConnectPopup';
import settingsIcon from '../../assets/icons/Settings.svg';
import gridIcon from '../../assets/icons/Grid.svg';
import penIcon from '../../assets/icons/Pen.svg';
import databaseIcon from '../../assets/icons/Database.svg';
import libraryIcon from '../../assets/icons/Library.svg';
import fileIcon from '../../assets/icons/File.svg';
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

  // Load projects and selected project from localStorage
  useEffect(() => {
    const savedProjects = localStorage.getItem('projects');
    if (savedProjects) {
      try {
        setProjects(JSON.parse(savedProjects));
      } catch {
        setProjects([]);
      }
    }
    // Load selected project ID
    const savedSelectedProjectId = localStorage.getItem('selectedProjectId');
    if (savedSelectedProjectId) {
      setSelectedProjectId(savedSelectedProjectId);
    }
  }, []);

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
    // Refresh sessions every 5 seconds
    const interval = setInterval(() => {
      void fetchSessions();
    }, 5000);
    return () => clearInterval(interval);
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
        // Clear selected project when creating new chat from sidebar
        // This makes it an unassigned chat
        localStorage.removeItem('selectedProjectId');
        setSelectedProjectId(null);
        window.dispatchEvent(new CustomEvent('projectSelected'));

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

  // Sessions are already filtered to only include unassigned ones from API
  // This function is kept for consistency but just returns all sessions
  const getUnassignedSessions = (): SessionInfo[] => {
    // All sessions in state are already unassigned (fetched with unassigned_only=true)
    return sessions;
  };

  const handleSessionClick = (sessionId: string) => {
    // Find the session to check if it has a project_id
    const session = sessions.find(s => s.session_id === sessionId);

    // If session doesn't have a project_id (unassigned), clear selectedProjectId
    if (session && !session.project_id) {
      localStorage.removeItem('selectedProjectId');
      setSelectedProjectId(null);
      // Dispatch event to notify other components
      window.dispatchEvent(new CustomEvent('projectSelected'));
    }

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

  const handleCreateProject = async (name: string, description?: string) => {
    try {
      const res = await createProject(name, description);
      if (res.success && res.project) {
        const newProject: Project = {
          id: res.project.id,
          name: res.project.name,
          description: res.project.description,
          createdAt: res.project.created_at || new Date().toISOString(),
        };
        const updatedProjects = [...projects, newProject];
        setProjects(updatedProjects);
        localStorage.setItem('projects', JSON.stringify(updatedProjects));
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
        {/* Logo Section */}
        <div className="p-4 border-b-2 border-gray-300 relative group">
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

        {/* Top Section */}
        <div className="p-4">
          {/* Navigation Items */}
          <div className="space-y-1">
            <button
              onClick={handleNewChat}
              className={`w-full flex items-center ${isCollapsed ? 'justify-center px-2' : 'gap-3 px-3'} py-2.5 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors text-left`}
              type="button"
              title={isCollapsed ? 'New chat' : undefined}
            >
              <img src={penIcon} alt="New chat" className="w-6 h-6" />
              {!isCollapsed && <span className="text-base font-medium">New chat</span>}
            </button>

            <button
              onClick={() => setIsDatabasePopupOpen(true)}
              className={`w-full flex items-center ${isCollapsed ? 'justify-center px-2' : 'gap-3 px-3'} py-2.5 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors text-left`}
              type="button"
              title={isCollapsed ? 'Connect Database' : undefined}
            >
              <img src={databaseIcon} alt="Connect Database" className="w-6 h-6" />
              {!isCollapsed && <span className="text-base font-medium">Connect Database</span>}
            </button>

            <button
              className={`w-full flex items-center ${isCollapsed ? 'justify-center px-2' : 'gap-3 px-3'} py-2.5 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors text-left`}
              type="button"
              title={isCollapsed ? 'Library' : undefined}
            >
              <img src={libraryIcon} alt="Library" className="w-6 h-6" />
              {!isCollapsed && <span className="text-base font-medium">Library</span>}
            </button>

            <button
              className={`w-full flex items-center ${isCollapsed ? 'justify-center px-2' : 'gap-3 px-3'} py-2.5 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors text-left`}
              type="button"
              title={isCollapsed ? 'Files' : undefined}
            >
              <img src={fileIcon} alt="Files" className="w-6 h-6" />
              {!isCollapsed && <span className="text-base font-medium">Files</span>}
            </button>

            <button
              onClick={() => setIsProjectModalOpen(true)}
              className={`w-full flex items-center ${isCollapsed ? 'justify-center px-2' : 'gap-3 px-3'} py-2.5 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors text-left`}
              type="button"
              title={isCollapsed ? 'Add Project' : undefined}
            >
              <img src={folderPlusIcon} alt="Add Project" className="w-6 h-6" />
              {!isCollapsed && <span className="text-base font-medium">Add Project</span>}
            </button>
          </div>
        </div>

        {/* Projects Section */}
        {projects.length > 0 && !isCollapsed && (
          <div className="px-4 py-3">
            <h2 className="text-base font-semibold text-gray-700 mb-2">Projects</h2>
            <div className="space-y-1">
              {projects.map((project) => (
                <button
                  key={project.id}
                  onClick={() => {
                    setSelectedProjectId(project.id);
                    localStorage.setItem('selectedProjectId', project.id);
                    // Dispatch custom event to notify other components
                    window.dispatchEvent(new CustomEvent('projectSelected'));
                    // Clear selected session when switching projects
                    if (onSessionSelect) {
                      onSessionSelect(null as any);
                    }
                  }}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors text-left ${selectedProjectId === project.id ? 'bg-gray-100 font-semibold' : ''}`}
                  type="button"
                >
                  <img src={folderIcon} alt="Folder" className="w-6 h-6" />
                  <span className="text-base font-medium truncate">{project.name}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Chats Section - Only show unassigned chats */}
        {!isCollapsed && (
          <div className="flex-1 overflow-y-auto px-4 py-3">
            <h2 className="text-base font-semibold text-gray-700 mb-2">Chats</h2>
            {isLoading ? (
              <div className="text-sm text-gray-500">Loading...</div>
            ) : getUnassignedSessions().length === 0 ? (
              <div className="text-sm text-gray-500">No unassigned chats yet</div>
            ) : (
              <div className="space-y-1">
                {getUnassignedSessions().map((session) => (
                  <button
                    key={session.session_id}
                    onClick={() => handleSessionClick(session.session_id)}
                    className={`w-full text-left px-3 py-2.5 rounded-lg transition-colors text-base ${currentSessionId === session.session_id
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
        )}

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

