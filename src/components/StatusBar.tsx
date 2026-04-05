import { useProjectStore } from '@/store/projectStore';

export function StatusBar() {
  const pixelsPerFoot = useProjectStore((s) => s.pixelsPerFoot);
  const currentPage = useProjectStore((s) => s.currentPage);
  const totalPages = useProjectStore((s) => s.totalPages);
  const projectName = useProjectStore((s) => s.projectName);
  const documents = useProjectStore((s) => s.documents);
  const toolModes = useProjectStore((s) => s.toolModes);

  const fn = (
    window as unknown as { __takeoffExport?: () => { quantity: string }[] }
  ).__takeoffExport;
  const rows = fn?.() ?? [];
  const markCount = rows.length;

  return (
    <footer className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t border-ost-border bg-gradient-to-b from-[#121722] to-[#0f141d] px-3 py-2 text-[11px] text-ost-muted">
      <span className="font-medium text-slate-300">{projectName || '—'}</span>
      <span>
        Plans: <span className="text-slate-200">{documents.length}</span>
      </span>
      <span>
        Scale: <span className="text-blue-300">{pixelsPerFoot} px/ft</span>
      </span>
      <span>
        Sheet {totalPages ? currentPage : '—'} / {totalPages || '—'}
      </span>
      <span>
        Marks (page): <span className="text-slate-200">{markCount}</span>
      </span>
      <span className="hidden sm:inline">
        {toolModes.continuousLinear && '● Continuous '}
        {toolModes.alignGrid && '● Grid '}
        {toolModes.backoffArea && '● Backout '}
        {!toolModes.continuousLinear &&
          !toolModes.alignGrid &&
          !toolModes.backoffArea &&
          'Standard modes'}
      </span>
    </footer>
  );
}
