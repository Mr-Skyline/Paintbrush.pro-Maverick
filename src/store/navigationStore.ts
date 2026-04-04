import { create } from 'zustand';

export type AppScreen =
  | 'projects'
  | 'new-project'
  | 'workspace'
  | 'battleship-lab';

interface NavState {
  screen: AppScreen;
  /** When in workspace, which project is open */
  openProjectId: string | null;
  setScreen: (s: AppScreen) => void;
  openWorkspace: (projectId: string) => void;
  goToProjects: () => void;
  goToNewProject: () => void;
  goToBattleshipLab: () => void;
}

export const useNavigationStore = create<NavState>((set) => ({
  screen: 'projects',
  openProjectId: null,
  setScreen: (screen) => set({ screen }),
  openWorkspace: (openProjectId) =>
    set({ screen: 'workspace', openProjectId }),
  goToProjects: () => set({ screen: 'projects', openProjectId: null }),
  goToNewProject: () => set({ screen: 'new-project' }),
  goToBattleshipLab: () => set({ screen: 'battleship-lab', openProjectId: null }),
}));
