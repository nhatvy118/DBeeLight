import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  createProject,
  createExternalProject,
  getProjects,
  deleteProject,
  listSharedProjects,
  url,
  type ExternalConnectionInput,
  type ProjectKind,
} from '../../services/api';
import ProjectModal from '../modals/ProjectModal';
import DeleteProjectModal from '../modals/DeleteProjectModal';
import ShareProjectModal from '../modals/ShareProjectModal';
import StorageModal from '../modals/StorageModal';
import { useOnboarding } from '../../context/OnboardingContext';
import { Icons, BeeBadge, type IconComponent } from '../../icons';
import { toast } from '../Toaster';
import type { AuthUser } from '../../context/AuthContext';

type Project = {
  id: string;
  name: string;
  description?: string;
  createdAt: string;
  kind: ProjectKind;
  sharedBy?: string | null;
};

type SidebarProps = {
  onSessionSelect?: (sessionId: string) => void;
  currentSessionId?: string | null;
  /** Close the mobile drawer (so a popped-open modal isn't behind it). No-op on desktop. */
  onRequestCloseDrawer?: () => void;
};

/** A primary navigation row in the sidebar. */
function NavItem({
  icon: Icon,
  label,
  onClick,
  collapsed,
  accent,
  tag,
}: {
  icon: IconComponent;
  label: string;
  onClick: () => void;
  collapsed: boolean;
  accent?: boolean;
  tag?: { text: string; tone: 'accent' | 'green' };
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
        background: 'transparent',
        border: '1px solid transparent',
        transition: 'all .14s',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--accent-soft)'; e.currentTarget.style.color = 'var(--accent-ink)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = accent ? 'var(--accent-ink)' : 'var(--text-soft)'; }}
    >
      <Icon size={19} />
      {!collapsed && <span style={{ flex: 1 }}>{label}</span>}
      {!collapsed && tag && (
        <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: 0, borderRadius: 5, padding: '1px 6px', flexShrink: 0,
          color: tag.tone === 'green' ? 'var(--green-ink)' : 'var(--accent-ink)',
          background: tag.tone === 'green' ? 'var(--green-soft)' : 'var(--accent-soft)' }}>{tag.text}</span>
      )}
    </button>
  );
}

function SectionLabel({ children, strong = false }: { children: ReactNode; strong?: boolean }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: strong ? 'var(--accent-ink)' : 'var(--text-faint)', padding: '0 12px', marginBottom: 8 }}>
      {children}
    </div>
  );
}

/** A row inside the account popup menu. `danger` paints it red (Log out). */
function MenuItem({
  icon: Icon,
  label,
  onClick,
  danger,
}: {
  icon: IconComponent;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="focusable"
      style={{
        width: '100%', display: 'flex', alignItems: 'center', gap: 11, padding: '10px 12px',
        borderRadius: 'var(--r-sm)', textAlign: 'left', fontSize: 14, fontWeight: 600,
        color: danger ? 'oklch(0.58 0.19 25)' : 'var(--text-soft)',
        background: 'transparent', border: 'none', transition: 'all .12s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = danger ? 'oklch(0.95 0.05 25)' : 'var(--surface-2)';
        if (!danger) e.currentTarget.style.color = 'var(--text)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent';
        if (!danger) e.currentTarget.style.color = 'var(--text-soft)';
      }}
    >
      <Icon size={18} />
      {label}
    </button>
  );
}

/** Profile button + account popup menu (Account settings / Storage / Help /
 *  Log out), ported from the Chat/ design prototype (sidebar.jsx ProfileMenu). */
function ProfileMenu({
  collapsed,
  user,
  onNavigate,
  onOpenStorage,
  onOpenHelp,
  onLogout,
}: {
  collapsed: boolean;
  user: AuthUser | null;
  onNavigate: (path: string) => void;
  onOpenStorage: () => void;
  onOpenHelp: () => void;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const initial = (user?.name || user?.email || 'U').slice(0, 1).toUpperCase();
  const name = user?.name || 'User';
  const email = user?.email || '';

  const Avatar = ({ size }: { size: number }) =>
    user?.picture ? (
      <img src={user.picture} alt={name} referrerPolicy="no-referrer"
        style={{ width: size, height: size, borderRadius: 99, objectFit: 'cover', flexShrink: 0 }} />
    ) : (
      <div style={{ width: size, height: size, borderRadius: 99, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'linear-gradient(145deg, var(--accent), var(--accent-strong))', color: 'var(--on-accent)', fontWeight: 800, fontSize: size * 0.42 }}>
        {initial}
      </div>
    );

  return (
    <div style={{ borderTop: '1px solid var(--border)', padding: collapsed ? '12px 0' : '12px 14px', position: 'relative' }}>
      {open && <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 40 }} />}
      {open && (
        <div className="card pop-shadow scale-in"
          style={{ position: 'absolute', bottom: 'calc(100% - 4px)', left: collapsed ? 8 : 14, right: collapsed ? 'auto' : 14, width: collapsed ? 224 : 'auto', zIndex: 41, borderRadius: 'var(--r)', padding: 8, transformOrigin: 'bottom' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '8px 10px 12px', borderBottom: '1px solid var(--border)', marginBottom: 6 }}>
            <Avatar size={38} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{email}</div>
            </div>
          </div>
          <MenuItem icon={Icons.Settings} label="Account settings" onClick={() => { setOpen(false); onNavigate('/account'); }} />
          <MenuItem icon={Icons.HardDrive} label="Storage" onClick={() => { setOpen(false); onOpenStorage(); }} />
          <MenuItem icon={Icons.Question} label="Help & support" onClick={() => { setOpen(false); onOpenHelp(); }} />
          {user?.is_admin && (
            <MenuItem icon={Icons.Server} label="Admin dashboard" onClick={() => { setOpen(false); onNavigate('/admin'); }} />
          )}
          <div style={{ height: 1, background: 'var(--border)', margin: '6px 4px' }} />
          <MenuItem icon={Icons.Logout} label="Log out" danger onClick={() => { setOpen(false); onLogout(); }} />
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="focusable"
        title={collapsed ? name : undefined}
        style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 11, justifyContent: collapsed ? 'center' : 'flex-start', padding: collapsed ? 6 : '8px 10px', borderRadius: 'var(--r-sm)', background: open ? 'var(--surface-2)' : 'transparent', border: 'none' }}
        onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; }}
        onMouseLeave={(e) => { if (!open) e.currentTarget.style.background = 'transparent'; }}
      >
        <Avatar size={36} />
        {!collapsed && (
          <>
            <div style={{ flex: 1, minWidth: 0, textAlign: 'left' }}>
              <div style={{ fontSize: 14, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{email}</div>
            </div>
            <Icons.ChevronDown size={16} style={{ color: 'var(--text-muted)', transition: 'transform .15s', transform: open ? 'rotate(180deg)' : 'none' }} />
          </>
        )}
      </button>
    </div>
  );
}

export default function Sidebar({ onSessionSelect, onRequestCloseDrawer }: SidebarProps) {
  const { user } = useAuth();
  const onboarding = useOnboarding();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null);
  const [projectToShare, setProjectToShare] = useState<Project | null>(null);
  const [isDeletingProject, setIsDeletingProject] = useState(false);
  const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
  const [isStorageModalOpen, setIsStorageModalOpen] = useState(false);
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

  // Let other views (e.g. the Chat "start a project" landing) open the New Project modal.
  useEffect(() => {
    const open = () => setIsProjectModalOpen(true);
    window.addEventListener('open-new-project', open);
    return () => window.removeEventListener('open-new-project', open);
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
        const [res, shared] = await Promise.all([getProjects(), listSharedProjects().catch(() => [])]);
        if (cancelled) return;
        const owned: Project[] = (res.success && res.projects)
          ? res.projects.map((p) => ({ id: p.id, name: p.name, description: p.description, createdAt: p.created_at ?? new Date().toISOString(), kind: p.kind ?? 'internal' }))
          : [];
        const sharedList: Project[] = shared
          .filter((s) => !owned.some((o) => o.id === s.id))
          .map((s) => ({ id: s.id, name: s.name, description: s.description, createdAt: s.shared_at ?? new Date().toISOString(), kind: 'internal' as ProjectKind, sharedBy: s.owner_name || s.owner_email }));
        const list = [...owned, ...sharedList];
        setProjects(list);
        localStorage.setItem('projects', JSON.stringify(list));
      } catch {
        if (!cancelled) setProjects([]);
      }
    };
    void loadProjects();
    return () => { cancelled = true; };
  }, [user]);

  // Shared optimistic insert + navigate for a freshly created project (internal or external).
  const onProjectCreated = (p: { id: string; name: string; description?: string; created_at?: string; kind?: ProjectKind }) => {
    const newProject: Project = {
      id: p.id,
      name: p.name,
      description: p.description ?? '',
      createdAt: p.created_at ?? new Date().toISOString(),
      kind: p.kind ?? 'internal',
    };
    const next = [newProject, ...projects];
    // Write localStorage before navigating so the Chat project view can resolve it.
    localStorage.setItem('projects', JSON.stringify(next));
    setProjects(next);
    setSelectedProjectId(p.id);
    navigate(`/chat/${p.id}`);
    if (onSessionSelect) onSessionSelect(null as unknown as string);
  };

  const handleCreateProject = async (name: string, description?: string) => {
    try {
      const res = await createProject(name, description);
      if (res.success && res.project) {
        onProjectCreated(res.project);
      } else {
        console.error('Failed to create project:', res);
        toast.error('Failed to create project');
      }
    } catch (err) {
      console.error('Failed to create project:', err);
      toast.error('Failed to create project');
    }
  };

  // External project: createExternalProject probes the DSN server-side and throws on failure.
  // We let the error propagate so ProjectModal can show it inline (and keep the form open).
  const handleCreateExternalProject = async (name: string, conn: ExternalConnectionInput, description?: string) => {
    const res = await createExternalProject(name, conn, description);
    if (res.success && res.project) {
      onProjectCreated(res.project);
    } else {
      throw new Error('error' in res ? res.error : 'Failed to create external project');
    }
  };

  const handleConfirmDeleteProject = async () => {
    if (!projectToDelete) return;
    const target = projectToDelete;
    setIsDeletingProject(true);
    try {
      const res = await deleteProject(target.id);
      if (!res.success) {
        toast.error(res.error || 'Failed to delete project');
        return;
      }
      setProjects((prev) => {
        const next = prev.filter((p) => p.id !== target.id);
        localStorage.setItem('projects', JSON.stringify(next));
        return next;
      });
      setProjectToDelete(null);
      // If we were viewing the deleted project, leave it.
      if (selectedProjectId === target.id) {
        setSelectedProjectId(null);
        navigate('/');
      }
      // No session refetch: deleting a project cascade-deletes only its assigned
      // sessions; the sidebar shows unassigned sessions (project_id IS NULL), unchanged.
    } catch (err) {
      console.error('Failed to delete project:', err);
      toast.error('Failed to delete project');
    } finally {
      setIsDeletingProject(false);
    }
  };

  const navigate = (path: string) => {
    window.history.pushState({}, '', path);
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  // Split projects into the two sections shown in the sidebar. A project lands in
  // exactly one list based on its `kind`, so creating an internal/external project
  // adds the row to the matching section.
  const internalProjects = projects.filter((p) => p.kind !== 'external');
  const externalProjects = projects.filter((p) => p.kind === 'external');

  // A single project row (button + dashboard/share/delete actions). Shared by both
  // sections; the section header already conveys internal vs external, so no inline badge.
  const renderProjectRow = (project: Project) => {
    const on = selectedProjectId === project.id;
    const isExternal = project.kind === 'external';
    return (
      <div
        key={project.id}
        style={{ position: 'relative', display: 'flex', alignItems: 'center' }}
      >
        <button
          type="button"
          className="focusable"
          onClick={() => {
            setSelectedProjectId(project.id);
            navigate(`/chat/${project.id}`);
            if (onSessionSelect) onSessionSelect(null as unknown as string);
          }}
          style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 11, padding: '9px 12px', paddingRight: 64, borderRadius: 'var(--r-sm)', textAlign: 'left', fontSize: 14,
            color: on ? 'var(--text)' : 'var(--text-soft)', background: on ? 'var(--surface)' : 'transparent', border: on ? '1px solid var(--border)' : '1px solid transparent' }}
          onMouseEnter={(e) => { if (!on) e.currentTarget.style.background = 'var(--surface-2)'; }}
          onMouseLeave={(e) => { if (!on) e.currentTarget.style.background = 'transparent'; }}
        >
          {isExternal
            ? <Icons.Database size={17} style={{ color: on ? 'var(--green-ink)' : 'var(--text-muted)', flexShrink: 0 }} />
            : <Icons.Folder size={17} style={{ color: on ? 'var(--accent-ink)' : 'var(--text-muted)', flexShrink: 0 }} />}
          <span style={{ flex: 1, minWidth: 0, display: 'inline-flex', alignItems: 'center', gap: 6, overflow: 'hidden' }}>
            <span style={{ fontWeight: on ? 700 : 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{project.name}</span>
            {project.sharedBy && <span title={`Shared by ${project.sharedBy}`} style={{ flexShrink: 0, fontSize: 10, fontWeight: 600, padding: '1px 5px', borderRadius: 4, background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}>Shared</span>}
          </span>
        </button>
        <button
          type="button"
          className="focusable"
          aria-label={`Open dashboard for ${project.name}`}
          title="Dashboard"
          onClick={(e) => { e.stopPropagation(); onRequestCloseDrawer?.(); navigate(`/dashboard/${project.id}`); }}
          style={{ position: 'absolute', right: 34, top: '50%', transform: 'translateY(-50%)', width: 26, height: 26, display: 'grid', placeItems: 'center', borderRadius: 6, border: 'none', background: 'transparent', color: 'var(--text-faint)', cursor: 'pointer', flexShrink: 0 }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-3)'; e.currentTarget.style.color = 'var(--accent-ink)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-faint)'; }}
        >
          <Icons.Chart size={15} />
        </button>
        <button
          type="button"
          className="focusable"
          aria-label={`Share project ${project.name}`}
          title="Share project"
          onClick={(e) => { e.stopPropagation(); setProjectToShare(project); }}
          style={{ position: 'absolute', right: 62, top: '50%', transform: 'translateY(-50%)', width: 26, height: 26, display: 'grid', placeItems: 'center', borderRadius: 6, border: 'none', background: 'transparent', color: 'var(--text-faint)', cursor: 'pointer', flexShrink: 0 }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-3)'; e.currentTarget.style.color = 'var(--accent-ink)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-faint)'; }}
        >
          <Icons.Share size={15} />
        </button>
        <button
          type="button"
          className="focusable"
          aria-label={`Delete project ${project.name}`}
          title="Delete project"
          onClick={(e) => { e.stopPropagation(); setProjectToDelete(project); }}
          style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', width: 26, height: 26, display: 'grid', placeItems: 'center', borderRadius: 6, border: 'none', background: 'transparent', color: 'var(--text-faint)', cursor: 'pointer', flexShrink: 0 }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-3)'; e.currentTarget.style.color = 'var(--danger, #d93025)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-faint)'; }}
        >
          <Icons.Trash size={15} />
        </button>
      </div>
    );
  };

  // Logout mirrors Header.handleLogout: clear the server cookie + local state,
  // then hard-navigate to /login so a logged-out shell never flashes.
  const handleLogout = async () => {
    try {
      await fetch(url('/api/auth/logout'), { method: 'POST', credentials: 'include' });
    } catch {
      // cookie may already be gone — leave the app anyway
    }
    try {
      localStorage.removeItem('projects');
      localStorage.removeItem('lastSessionId');
      localStorage.removeItem('lastSessionIdForProject');
    } catch {
      // storage blocked — ignore
    }
    window.location.replace('/login');
  };

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
            {!isCollapsed && <span style={{ fontSize: 19, fontWeight: 800, letterSpacing: '-.02em' }}>DBeeLight</span>}
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
          <NavItem icon={Icons.FolderPlus} label="New project" collapsed={isCollapsed} accent onClick={() => { onRequestCloseDrawer?.(); setIsProjectModalOpen(true); }} />
        </div>

        {/* scroll area: projects + history */}
        <div style={{ flex: 1, overflowY: 'auto', padding: isCollapsed ? '12px 0' : '14px 14px', display: 'flex', flexDirection: 'column', gap: 18 }}>
          {!isCollapsed && (
            <>
              <div>
                <SectionLabel strong>Internal</SectionLabel>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {internalProjects.length === 0 ? (
                    <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '4px 12px' }}>No internal projects yet</div>
                  ) : internalProjects.map(renderProjectRow)}
                </div>
              </div>
              <div>
                <SectionLabel strong>External</SectionLabel>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {externalProjects.length === 0 ? (
                    <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '4px 12px' }}>No external projects yet</div>
                  ) : externalProjects.map(renderProjectRow)}
                </div>
              </div>
            </>
          )}
        </div>

        {/* user profile + account menu */}
        <ProfileMenu
          collapsed={isCollapsed}
          user={user}
          onNavigate={navigate}
          onOpenStorage={() => { onRequestCloseDrawer?.(); setIsStorageModalOpen(true); }}
          onOpenHelp={() => { onRequestCloseDrawer?.(); onboarding.open(); }}
          onLogout={() => { void handleLogout(); }}
        />
      </aside>

      <ProjectModal
        isOpen={isProjectModalOpen}
        onClose={() => setIsProjectModalOpen(false)}
        onCreateInternal={handleCreateProject}
        onCreateExternal={handleCreateExternalProject}
      />

      <StorageModal open={isStorageModalOpen} onClose={() => setIsStorageModalOpen(false)} />

      {projectToDelete && (
        <DeleteProjectModal
          projectId={projectToDelete.id}
          projectName={projectToDelete.name}
          isDeleting={isDeletingProject}
          onClose={() => setProjectToDelete(null)}
          onConfirm={() => void handleConfirmDeleteProject()}
        />
      )}

      {projectToShare && (
        <ShareProjectModal
          project={{ id: projectToShare.id, name: projectToShare.name }}
          onClose={() => setProjectToShare(null)}
        />
      )}
    </>
  );
}

