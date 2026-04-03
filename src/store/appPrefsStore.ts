import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AppPrefs {
  lastProjectId: string | null;
  setLastProjectId: (id: string | null) => void;
}

export const useAppPrefsStore = create<AppPrefs>()(
  persist(
    (set) => ({
      lastProjectId: null,
      setLastProjectId: (lastProjectId) => set({ lastProjectId }),
    }),
    { name: 'paintbrush-app-prefs' }
  )
);
