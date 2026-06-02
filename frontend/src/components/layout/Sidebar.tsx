import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  createSession,
  getSessions,
  createProject,
  getProjects,
  listReceivedShares,
  connectExternalDb,
  disconnectExternalDb,
  getDbConnectionStatus,
  type ReceivedShare,
  type SessionInfo,
} from '../../services/api';
import ProjectModal from '../modals/ProjectModal';
import DatabaseConnectPopup, { type DatabaseConnectionData } from '../modals/DatabaseConnectPopup';
import { encryptPassword, decryptPassword } from '../../utils/crypto';
import { Icons, BeeBadge, type IconComponent } from '../../icons';

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

/** A primary navigation row in the sidebar. */
function NavItem({
  icon: Icon,
  label,
  onClick,
  collapsed,
  accent,
}: {
  icon: IconComponent;
  label: string;
  onClick: () => void;
  collapsed: boolean;
  accent?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={collapsed ? label : undefined}
      type="button"
      className="focusable"
      style={{
        width: '100%', display: 'flex', alignItems: 'center', gap: 12,
        justifyContent: collapsed ? 'center' : 'flex-start',
        padding: collapsed ? 10 : '10px 12px', borderRadius: 'var(--r-sm)',
        fontSize: 14.5, fontWeight: 600, textAlign: 'left',
        color: accent ? 'var(--accent-ink)' : 'var(--text-soft)',
        background: accent ? 'var(--accent-soft)' : 'transparent',
        border: accent ? '1px solid var(--accent-soft-2)' : '1px solid transparent',
        transition: 'all .14s',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = accent ? 'var(--accent-soft)' : 'var(--surface-2)'; if (!accent) e.currentTarget.style.color = 'var(--text)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = accent ? 'var(--accent-soft)' : 'transparent'; if (!accent) e.currentTarget.style.color = 'var(--text-soft)'; }}
    >
      <Icon size={19} />
      {!collapsed && <span>{label}</span>}
    </button>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-faint)', padding: '0 12px', marginBottom: 8 }}>
      {children}
    </div>
  );
}

export default function Sidebar({ onSessionSelect, currentSessionId }: SidebarProps) {
  const { user } = useAuth();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [receivedShares, setReceivedShares] = useState<ReceivedShare[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [projects, setProjects] = useState<Project[]>([]);
  const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
  const [isDatabasePopupOpen, setIsDatabasePopupOpen] = useState(false);
  const [connectedDb, setConnectedDb] = useState<DatabaseConnectionData | null>(null);

  const saveConnectedDb = async (data: DatabaseConnectionData) => {
    const encryptedPassword = await encryptPassword(data.password);
    localStorage.setItem('connectedDb', JSON.stringify({ ...data, password: encryptedPassword }));
  };

  const clearConnectedDb = () => {
    localStorage.removeItem('connectedDb');
    setConnectedDb(null);
  };

  // On mount: load + decrypt stored connection, then verify backend is still connected.
  useEffect(() => {
    const stored = localStorage.getItem('connectedDb');
    if (!stored) return;

    (async () => {
      try {
        const parsed = JSON.parse(stored) as DatabaseConnectionData;
        const plainPassword = await decryptPassword(parsed.password);
        const data = { ...parsed, password: plainPassword };

        const status = await getDbConnectionStatus();
        if (status.success) {
          setConnectedDb(data);
        } else {
          clearConnectedDb();
        }
      } catch {
        clearConnectedDb();
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [isCollapsed, setIsCollapsed] = useState<boolean>(false);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

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

  // Load shares received by the current user.
  useEffect(() => {
    if (!user) {
      setReceivedShares([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const list = await listReceivedShares();
        if (!cancelled) setReceivedShares(list);
      } catch (e) {
        console.error('Failed to load received shares:', e);
      }
    })();
    return () => { cancelled = true; };
  }, [user]);

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

  const handleDatabaseConnect = async (connectionData: DatabaseConnectionData): Promise<{ success: boolean; error?: string }> => {
    const result = await connectExternalDb({
      host: connectionData.server,
      port: parseInt(connectionData.port, 10) || 5432,
      database: connectionData.databaseName,
      username: connectionData.username,
      password: connectionData.password,
    });
    if (result.success) {
      setConnectedDb(connectionData);
      await saveConnectedDb(connectionData);
    }
    return { success: result.success, error: result.success ? undefined : result.message };
  };

  const handleDatabaseDisconnect = async () => {
    await disconnectExternalDb();
    clearConnectedDb();
  };

  const navigate = (path: string) => {
    window.history.pushState({}, '', path);
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  const PERM: Record<string, { label: string; color: string }> = {
    view_only: { label: 'View', color: 'var(--text-muted)' },
    read_data: { label: 'Read', color: 'var(--info)' },
    edit_data: { label: 'Edit', color: 'var(--green-ink)' },
  };
  const userInitial = (user?.name || user?.email || 'U').slice(0, 1).toUpperCase();
  const unassigned = getUnassignedSessions();

  return (
    <>
      <aside
        style={{
          width: isCollapsed ? 74 : 286, flexShrink: 0, height: '100%',
          display: 'flex', flexDirection: 'column',
          background: 'var(--bg-tint)', borderRight: '1px solid var(--border)',
          transition: 'width .26s cubic-bezier(.4,0,.2,1)',
        }}
      >
        {/* header / logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: isCollapsed ? '16px 0' : '16px 18px', justifyContent: isCollapsed ? 'center' : 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <BeeBadge size={36} />
            {!isCollapsed && <span style={{ fontSize: 19, fontWeight: 800, letterSpacing: '-.02em' }}>LightDBee</span>}
          </div>
          {!isCollapsed && (
            <button onClick={() => setIsCollapsed(true)} title="Collapse" type="button" className="focusable"
              style={{ width: 32, height: 32, borderRadius: 8, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', background: 'transparent', border: 'none' }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}>
              <Icons.Sidebar size={19} />
            </button>
          )}
        </div>

        {isCollapsed && (
          <div style={{ display: 'grid', placeItems: 'center', paddingBottom: 6 }}>
            <button onClick={() => setIsCollapsed(false)} title="Expand" type="button" className="focusable"
              style={{ width: 36, height: 36, borderRadius: 8, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', background: 'transparent', border: 'none' }}>
              <Icons.Sidebar size={19} />
            </button>
          </div>
        )}

        {/* primary nav */}
        <div style={{ padding: isCollapsed ? '6px 12px' : '6px 14px', display: 'flex', flexDirection: 'column', gap: 3 }}>
          <NavItem icon={Icons.NewChat} label="New chat" collapsed={isCollapsed} accent onClick={() => { void handleNewChat(); }} />
          <NavItem icon={Icons.Database} label={connectedDb ? 'Data sources' : 'Connect data'} collapsed={isCollapsed} onClick={() => setIsDatabasePopupOpen(true)} />
          <NavItem icon={Icons.FolderPlus} label="New project" collapsed={isCollapsed} onClick={() => setIsProjectModalOpen(true)} />
        </div>

        {/* connected-data status */}
        {!isCollapsed && (
          <div style={{ padding: '10px 14px 4px' }}>
            {connectedDb ? (
              <button onClick={() => setIsDatabasePopupOpen(true)} type="button" className="focusable"
                style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 11, padding: '11px 13px', borderRadius: 'var(--r-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}>
                <span style={{ position: 'relative', width: 32, height: 32, borderRadius: 9, display: 'grid', placeItems: 'center', background: 'var(--green-soft)', color: 'var(--green-ink)', flexShrink: 0 }}>
                  <Icons.Database size={17} />
                  <span style={{ position: 'absolute', right: -2, bottom: -2, width: 11, height: 11, borderRadius: 99, background: 'var(--green)', border: '2px solid var(--bg-tint)' }} />
                </span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: 'block', fontSize: 13.5, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{connectedDb.databaseName}</span>
                  <span style={{ display: 'block', fontSize: 11.5, color: 'var(--green-ink)', fontWeight: 600 }}>Connected</span>
                </span>
                <Icons.ChevronRight size={15} style={{ color: 'var(--text-faint)' }} />
              </button>
            ) : (
              <button onClick={() => setIsDatabasePopupOpen(true)} type="button" className="focusable"
                style={{ width: '100%', textAlign: 'left', padding: 13, borderRadius: 'var(--r-sm)', border: '1.5px dashed var(--border-strong)', background: 'var(--surface)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, fontSize: 13.5, fontWeight: 700, color: 'var(--accent-ink)' }}>
                  <Icons.Plus size={16} /> Connect a database
                </div>
                <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>Start asking questions about your data.</p>
              </button>
            )}
          </div>
        )}

        {/* scroll area: projects + shared + history */}
        <div style={{ flex: 1, overflowY: 'auto', padding: isCollapsed ? '12px 0' : '14px 14px', display: 'flex', flexDirection: 'column', gap: 18 }}>
          {!isCollapsed && (
            <div>
              <SectionLabel>Projects</SectionLabel>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {projects.length === 0 ? (
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '4px 12px' }}>No projects yet</div>
                ) : projects.map((project) => {
                  const on = selectedProjectId === project.id;
                  return (
                    <button
                      key={project.id}
                      type="button"
                      className="focusable"
                      onClick={() => {
                        setSelectedProjectId(project.id);
                        navigate(`/chat/${project.id}`);
                        if (onSessionSelect) onSessionSelect(null as unknown as string);
                      }}
                      style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 11, padding: '9px 12px', borderRadius: 'var(--r-sm)', textAlign: 'left', fontSize: 14,
                        color: on ? 'var(--text)' : 'var(--text-soft)', background: on ? 'var(--surface)' : 'transparent', border: on ? '1px solid var(--border)' : '1px solid transparent' }}
                      onMouseEnter={(e) => { if (!on) e.currentTarget.style.background = 'var(--surface-2)'; }}
                      onMouseLeave={(e) => { if (!on) e.currentTarget.style.background = 'transparent'; }}
                    >
                      <Icons.Folder size={17} style={{ color: on ? 'var(--accent-ink)' : 'var(--text-muted)', flexShrink: 0 }} />
                      <span style={{ flex: 1, fontWeight: on ? 700 : 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{project.name}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {!isCollapsed && receivedShares.length > 0 && (
            <div>
              <SectionLabel>Shared with me</SectionLabel>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {receivedShares.map((s) => {
                  const isAccepted = !!s.accepted_at && !!s.forked_session_id;
                  const target = isAccepted
                    ? `/chat/${s.project_id}/${s.forked_session_id}`
                    : `/share/accept/${encodeURIComponent(s.accept_token)}`;
                  const ownerName = s.owner_name || s.owner_email || 'Unknown';
                  const perm = PERM[s.permission] ?? PERM.view_only;
                  return (
                    <button key={s.recipient_id} onClick={() => navigate(target)} type="button" className="focusable"
                      style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 11, padding: '9px 12px', borderRadius: 'var(--r-sm)', textAlign: 'left', color: 'var(--text-soft)', background: 'transparent', border: 'none' }}
                      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}>
                      <span style={{ width: 26, height: 26, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--surface-3)', color: 'var(--text-soft)', fontSize: 11, fontWeight: 800 }}>{ownerName[0]}</span>
                      <span style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ display: 'block', fontSize: 13.5, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.session_name || 'Shared chat'}</span>
                        <span style={{ display: 'block', fontSize: 11.5, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{isAccepted ? `from ${ownerName}` : `pending — ${ownerName}`}</span>
                      </span>
                      <span style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.03em', color: perm.color, flexShrink: 0 }}>{perm.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {!isCollapsed && (
            <div>
              <SectionLabel>Chat history</SectionLabel>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {isLoading ? (
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '4px 12px' }}>Loading…</div>
                ) : unassigned.length === 0 ? (
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '4px 12px' }}>No chats yet</div>
                ) : unassigned.map((session) => {
                  const on = currentSessionId === session.session_id;
                  return (
                    <button key={session.session_id} onClick={() => handleSessionClick(session.session_id)} type="button" className="focusable"
                      style={{ width: '100%', display: 'block', padding: '9px 12px', borderRadius: 'var(--r-sm)', textAlign: 'left', fontSize: 14, fontWeight: on ? 700 : 500,
                        color: on ? 'var(--text)' : 'var(--text-soft)', background: on ? 'var(--surface)' : 'transparent',
                        border: on ? '1px solid var(--border)' : '1px solid transparent',
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      onMouseEnter={(e) => { if (!on) e.currentTarget.style.background = 'var(--surface-2)'; }}
                      onMouseLeave={(e) => { if (!on) e.currentTarget.style.background = 'transparent'; }}>
                      {formatSessionName(session)}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* user profile */}
        <div style={{ borderTop: '1px solid var(--border)', padding: isCollapsed ? '12px 0' : '12px 14px' }}>
          <button
            type="button"
            className="focusable"
            onClick={() => { navigate('/account'); }}
            title="Account settings"
            style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 11, justifyContent: isCollapsed ? 'center' : 'flex-start', padding: isCollapsed ? 6 : '8px 10px', borderRadius: 'var(--r-sm)', background: 'transparent', border: 'none' }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            {user?.picture ? (
              <img src={user.picture} alt={user.name || user.email || 'User'} style={{ width: 36, height: 36, borderRadius: 99, objectFit: 'cover', flexShrink: 0 }} referrerPolicy="no-referrer" />
            ) : (
              <div style={{ width: 36, height: 36, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'linear-gradient(145deg, var(--accent), var(--accent-strong))', color: 'var(--on-accent)', fontWeight: 800, fontSize: 15 }}>{userInitial}</div>
            )}
            {!isCollapsed && (
              <div style={{ flex: 1, minWidth: 0, textAlign: 'left' }}>
                <div style={{ fontSize: 14, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user?.name || 'User'}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user?.email || ''}</div>
              </div>
            )}
          </button>
        </div>
      </aside>

      <ProjectModal
        isOpen={isProjectModalOpen}
        onClose={() => setIsProjectModalOpen(false)}
        onCreate={handleCreateProject}
      />

      <DatabaseConnectPopup
        isOpen={isDatabasePopupOpen}
        onClose={() => setIsDatabasePopupOpen(false)}
        onConnect={handleDatabaseConnect}
        onDisconnect={handleDatabaseDisconnect}
        connectedDb={connectedDb}
        isInProject={!!selectedProjectId}
      />
    </>
  );
}

