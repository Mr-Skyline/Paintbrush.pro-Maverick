import { deleteProjectFromIdb, listRegistry } from '@/lib/indexedProjectDb';
import { loadProjectFromIndexedDb } from '@/lib/projectPersistence';
import { pickWorkspaceDirectory } from '@/lib/fsProjectAccess';
import { saveFsRootHandle } from '@/lib/indexedProjectDb';
import { useNavigationStore } from '@/store/navigationStore';
import { useEffect, useState } from 'react';

export function ProjectListScreen() {
  const [entries, setEntries] = useState<
    Awaited<ReturnType<typeof listRegistry>>
  >([]);
  const goNew = useNavigationStore((s) => s.goToNewProject);
  const goBattleshipLab = useNavigationStore((s) => s.goToBattleshipLab);
  const openWorkspace = useNavigationStore((s) => s.openWorkspace);

  const refresh = () => {
    void listRegistry().then(setEntries);
  };

  useEffect(() => {
    refresh();
  }, []);

  const open = async (id: string) => {
    await loadProjectFromIndexedDb(id);
    openWorkspace(id);
  };

  const remove = async (id: string) => {
    if (!confirm('Delete this project from browser storage?')) return;
    await deleteProjectFromIdb(id);
    refresh();
  };

  const linkFolder = async () => {
    const dir = await pickWorkspaceDirectory();
    if (dir) {
      await saveFsRootHandle(dir);
      alert('Workspace folder linked. Saves can sync to disk from the toolbar.');
    }
  };

  return (
    <div className="flex min-h-full flex-col bg-ost-bg p-8 text-slate-100">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Projects
          </h1>
          <p className="mt-1 text-sm text-ost-muted">
            OST-style takeoffs — stored in IndexedDB; optional disk folder sync
            (Chrome/Edge).
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={linkFolder}
            className="rounded-lg border border-ost-border px-4 py-2 text-sm hover:bg-white/5"
          >
            Link workspace folder…
          </button>
          <button
            type="button"
            onClick={goBattleshipLab}
            className="rounded-lg border border-indigo-500/40 bg-indigo-600/20 px-4 py-2 text-sm hover:bg-indigo-500/30"
          >
            Battleship AI Lab
          </button>
          <button
            type="button"
            onClick={goNew}
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-semibold hover:bg-blue-500"
          >
            New project
          </button>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {entries.length === 0 ? (
          <div className="col-span-full rounded-xl border border-dashed border-ost-border p-12 text-center text-ost-muted">
            No saved projects yet. Create a new project and upload your PDF plan
            set.
          </div>
        ) : (
          entries.map((e) => (
            <div
              key={e.id}
              className="flex flex-col rounded-xl border border-ost-border bg-ost-panel p-4 shadow-lg"
            >
              <div className="mb-3 h-24 rounded-lg bg-gradient-to-br from-slate-800 to-slate-900" />
              <h2 className="font-semibold text-white">{e.name}</h2>
              <p className="mt-1 text-xs text-ost-muted">
                Modified {new Date(e.updatedAt).toLocaleString()}
              </p>
              <div className="mt-4 flex gap-2">
                <button
                  type="button"
                  onClick={() => open(e.id)}
                  className="flex-1 rounded-lg bg-emerald-700 py-2 text-sm font-medium hover:bg-emerald-600"
                >
                  Open
                </button>
                <button
                  type="button"
                  onClick={() => remove(e.id)}
                  className="rounded-lg border border-red-900/50 px-3 py-2 text-xs text-red-300 hover:bg-red-950/40"
                >
                  Delete
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
