import { useProjectStore } from '@/store/projectStore';
import { applyConditionVisualToFabricObject } from '@/utils/conditionStyle';
import { fabric } from 'fabric';

export function RightSidebarProperties() {
  const rightOpen = useProjectStore((s) => s.rightOpen);
  const toggleRight = useProjectStore((s) => s.toggleRight);
  const nid = useProjectStore((s) => s.selectedMarkNid);
  const meta = useProjectStore((s) => s.selectedMarkMeta);
  const conditions = useProjectStore((s) => s.conditions);

  if (!rightOpen) {
    return (
      <button
        type="button"
        onClick={toggleRight}
        className="w-8 shrink-0 border-l border-ost-border bg-ost-panel py-2 text-xs text-ost-muted hover:bg-white/5"
      >
        ◂
      </button>
    );
  }

  const reassign = (conditionId: string) => {
    const c = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
      .__takeoffCanvas;
    if (!c || !nid) return;
    const o = c
      .getObjects()
      .find((x) => (x as fabric.Object & { nid?: string }).nid === nid);
    if (!o) return;
    const cond = conditions.find((x) => x.id === conditionId);
    if (!cond) return;
    const ext = o as fabric.Object & { conditionIds?: string[] };
    ext.set({ conditionIds: [conditionId] });
    applyConditionVisualToFabricObject(o, [conditionId], conditions);
    o.setCoords();
    c.requestRenderAll();
    useProjectStore.getState().setSelectedMark(nid, {
      ...meta,
      conditionIds: [conditionId],
    });
  };

  return (
    <aside className="flex w-72 shrink-0 flex-col border-l border-ost-border bg-gradient-to-b from-[#131925] to-[#10141d]">
      <div className="flex items-center justify-between border-b border-ost-border px-3 py-3">
        <div>
          <span className="text-[11px] font-semibold uppercase text-ost-muted">
            Inspector
          </span>
          <p className="mt-0.5 text-sm font-medium text-slate-100">Selected mark</p>
        </div>
        <button
          type="button"
          onClick={toggleRight}
          className="text-ost-muted hover:text-white"
        >
          ▸
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 text-sm">
        {!nid ? (
          <p className="rounded border border-ost-border/70 bg-black/20 p-2 text-ost-muted">
            Select a mark on the canvas to inspect and reassign it.
          </p>
        ) : (
          <>
            <div className="mb-2 text-xs uppercase tracking-wide text-ost-muted">Mark ID</div>
            <div className="mb-4 rounded border border-ost-border/70 bg-black/20 p-2 font-mono text-xs break-all">
              {nid}
            </div>
            <div className="mb-2 text-xs uppercase tracking-wide text-ost-muted">Type</div>
            <div className="mb-4 rounded border border-ost-border/70 bg-black/20 p-2">
              {meta?.markType ?? '—'}
            </div>
            {meta?.lengthFt != null && (
              <>
                <div className="mb-2 text-xs uppercase tracking-wide text-ost-muted">Length</div>
                <div className="mb-4 rounded border border-ost-border/70 bg-black/20 p-2">
                  {meta.lengthFt.toFixed(2)} LF
                </div>
              </>
            )}
            {meta?.areaSf != null && (
              <>
                <div className="mb-2 text-xs uppercase tracking-wide text-ost-muted">Area</div>
                <div className="mb-4 rounded border border-ost-border/70 bg-black/20 p-2">
                  {meta.areaSf.toFixed(2)} SF
                </div>
              </>
            )}
            <div className="mb-2 text-xs uppercase tracking-wide text-ost-muted">Notes</div>
            <div className="mb-4 rounded border border-ost-border/70 bg-black/20 p-2 text-ost-muted">
              {meta?.notes ?? '—'}
            </div>
            <div className="mb-2 text-xs uppercase tracking-wide text-ost-muted">Reassign condition</div>
            <select
              className="w-full rounded border border-ost-border bg-black/40 px-2 py-2 text-sm"
              value=""
              onChange={(e) => {
                if (e.target.value) reassign(e.target.value);
              }}
            >
              <option value="">Choose…</option>
              {conditions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </>
        )}
      </div>
    </aside>
  );
}
