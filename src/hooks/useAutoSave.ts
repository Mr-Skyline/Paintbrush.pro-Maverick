import { saveProjectToIndexedDb } from '@/lib/projectPersistence';
import { useProjectStore } from '@/store/projectStore';
import { useEffect, useRef } from 'react';

const INTERVAL_MS = 30_000;

/** Auto-save full `project.ost.json` to IndexedDB while workspace is open. */
export function useAutoSave(enabled: boolean) {
  const projectId = useProjectStore((s) => s.projectId);
  const tickRef = useRef(0);

  useEffect(() => {
    if (!enabled || !projectId) return;
    const id = window.setInterval(async () => {
      try {
        await saveProjectToIndexedDb();
        tickRef.current += 1;
      } catch (e) {
        console.warn('Auto-save failed', e);
      }
    }, INTERVAL_MS);
    return () => clearInterval(id);
  }, [enabled, projectId]);

  return tickRef;
}
