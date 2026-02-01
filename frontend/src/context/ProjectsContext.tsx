import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { getProjects, type ProjectItem } from '../services/api';

type ProjectsContextValue = {
  projects: ProjectItem[];
  isLoading: boolean;
  refetchProjects: () => Promise<void>;
};

const ProjectsContext = createContext<ProjectsContextValue | null>(null);

export function ProjectsProvider({ children }: { children: React.ReactNode }) {
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refetchProjects = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await getProjects();
      if (res.success) {
        setProjects(res.projects ?? []);
      } else {
        setProjects([]);
      }
    } catch {
      setProjects([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refetchProjects();
  }, [refetchProjects]);

  return (
    <ProjectsContext.Provider value={{ projects, isLoading, refetchProjects }}>
      {children}
    </ProjectsContext.Provider>
  );
}

export function useProjects(): ProjectsContextValue {
  const ctx = useContext(ProjectsContext);
  if (!ctx) {
    return {
      projects: [],
      isLoading: false,
      refetchProjects: async () => {},
    };
  }
  return ctx;
}
