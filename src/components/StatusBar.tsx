import { useProjectStore } from '@/store/projectStore';

export function StatusBar() {
  const pixelsPerFoot = useProjectStore((s) => s.pixelsPerFoot);
  const currentPage = useProjectStore((s) => s.currentPage);
  const totalPages = useProjectStore((s) => s.totalPages);
  const projectName = useProjectStore((s) => s.projectName);
  const toolModes = useProjectStore((s) => s.toolModes);

  const fn = (
    window as unknown as { __takeoffExport?: () => { quantity: string }[] }
  ).__takeoffExport;
  const rows = fn?.() ?? [];
  const markCount = rows.length;

  return (
    <footer className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t border-ost-border bg-ost-panel px-3 py-1.5 text-[11px] text-ost-muted">
      <span className="font-medium text-slate-300">{projectName || '—'}</span>
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
