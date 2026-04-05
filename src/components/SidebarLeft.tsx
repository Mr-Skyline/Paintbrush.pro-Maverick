import { ConditionEditorModal } from '@/components/ConditionEditorModal';
import { useProjectStore } from '@/store/projectStore';
import type { ResultKind } from '@/types';
import { linePatternToDashArray } from '@/utils/conditionStyle';
import { useEffect, useMemo, useState } from 'react';

const KIND_LABEL: Record<ResultKind, string> = {
  linear: 'Linear (LF)',
  area_gross: 'Area gross (SF)',
  area_net: 'Area net (SF)',
  count: 'Count',
  assembly: 'Assembly',
};

export function SidebarLeft() {
  const leftCollapsed = useProjectStore((s) => s.leftCollapsed);
  const toggleLeft = useProjectStore((s) => s.toggleLeft);
  const conditions = useProjectStore((s) => s.conditions);
  const search = useProjectStore((s) => s.conditionSearch);
  const setSearch = useProjectStore((s) => s.setConditionSearch);
  const selected = useProjectStore((s) => s.selectedConditionIds);
  const toggleSel = useProjectStore((s) => s.toggleSelectCondition);
  const addCondition = useProjectStore((s) => s.addCondition);
  const currentPage = useProjectStore((s) => s.currentPage);
  const totalPages = useProjectStore((s) => s.totalPages);
  const setPage = useProjectStore((s) => s.setPage);
  const documents = useProjectStore((s) => s.documents);
  const activeDocumentId = useProjectStore((s) => s.activeDocumentId);
  const setActiveDocument = useProjectStore((s) => s.setActiveDocument);
  const openUploadPicker = () => {
    window.dispatchEvent(new Event('takeoff:open-upload-picker'));
  };
  const [phaseOpen, setPhaseOpen] = useState(true);
  const [docsOpen, setDocsOpen] = useState(true);
  const [editingConditionId, setEditingConditionId] = useState<string | null>(
    null
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return conditions;
    return conditions.filter((c) => c.name.toLowerCase().includes(q));
  }, [conditions, search]);

  if (leftCollapsed) {
    return (
      <button
        type="button"
        onClick={toggleLeft}
        className="w-8 shrink-0 border-r border-ost-border bg-ost-panel py-2 text-xs text-ost-muted hover:bg-white/5"
      >
        ▸
      </button>
    );
  }

  return (
    <aside className="flex w-80 shrink-0 flex-col border-r border-ost-border bg-gradient-to-b from-[#131925] to-[#10141d]">
      <div className="flex items-center justify-between border-b border-ost-border px-3 py-3">
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wide text-ost-muted">
            Workspace
          </span>
          <p className="mt-0.5 text-sm font-medium text-slate-100">Plans & Conditions</p>
        </div>
        <button
          type="button"
          onClick={toggleLeft}
          className="rounded px-2 py-1 text-ost-muted hover:bg-white/10"
        >
          ◂
        </button>
      </div>

      <div className="border-b border-ost-border p-3">
        <button
          type="button"
          onClick={() => setDocsOpen(!docsOpen)}
          className="flex w-full items-center justify-between text-left text-sm font-medium text-slate-100"
        >
          Plan set (PDFs)
          <span className="text-ost-muted">{docsOpen ? '−' : '+'}</span>
        </button>
        {docsOpen && (
          <>
            <button
              type="button"
              onClick={openUploadPicker}
              className="mt-2 w-full rounded border border-blue-500/40 bg-blue-600/15 px-2 py-1 text-[11px] font-medium text-blue-100 hover:bg-blue-600/25"
            >
              + Upload plan PDFs
            </button>
            <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs">
              {documents.length === 0 ? (
                <li className="rounded border border-ost-border/70 bg-black/20 px-2 py-2 text-ost-muted">
                  No sheets yet. Upload PDFs to begin takeoff.
                </li>
              ) : (
                documents.map((d) => (
                  <li key={d.id}>
                    <button
                      type="button"
                      onClick={() => setActiveDocument(d.id)}
                      className={`w-full truncate rounded border px-2 py-1 text-left hover:bg-white/10 ${
                        d.id === activeDocumentId
                          ? 'border-emerald-600/60 bg-emerald-900/30 text-emerald-100'
                          : 'border-ost-border/60 bg-black/20 text-slate-300'
                      }`}
                    >
                      {d.name}{' '}
                      <span className="text-ost-muted">({d.pageCount} pg)</span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          </>
        )}
      </div>

      <div className="border-b border-ost-border p-3">
        <button
          type="button"
          onClick={() => setPhaseOpen(!phaseOpen)}
          className="flex w-full items-center justify-between text-left text-sm font-medium text-slate-100"
        >
          Sheet navigator
          <span className="text-ost-muted">{phaseOpen ? '−' : '+'}</span>
        </button>
        {phaseOpen && (
          <div className="mt-2 max-h-36 overflow-y-auto text-sm text-ost-muted">
            {totalPages === 0 ? (
              <p className="rounded border border-ost-border/70 bg-black/20 px-2 py-2 text-xs">
                Open a PDF to list sheets.
              </p>
            ) : (
              <ul className="space-y-1">
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                  <li key={p}>
                    <button
                      type="button"
                      onClick={() => setPage(p)}
                      className={`w-full rounded px-2 py-0.5 text-left text-xs hover:bg-white/10 ${
                        p === currentPage
                          ? 'border border-blue-600/70 bg-blue-600/25 text-white'
                          : 'border border-ost-border/60 bg-black/20'
                      }`}
                    >
                      Sheet {p}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <div className="border-b border-ost-border p-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase text-ost-muted">
            Conditions
          </span>
          <button
            type="button"
            onClick={() => {
              const name = window.prompt('Condition name');
              if (!name) return;
              const kind = window.prompt(
                'Result type: linear | area_gross | area_net | count | assembly',
                'linear'
              ) as ResultKind | null;
              const ok: ResultKind[] = [
                'linear',
                'area_gross',
                'area_net',
                'count',
                'assembly',
              ];
              const rk = ok.includes(kind as ResultKind)
                ? (kind as ResultKind)
                : 'linear';
              addCondition({
                name,
                color:
                  '#' +
                  Math.floor(Math.random() * 0xffffff)
                    .toString(16)
                    .padStart(6, '0'),
                resultKind: rk,
              });
            }}
            className="rounded bg-blue-600 px-2 py-0.5 text-[11px] font-medium hover:bg-blue-500"
          >
            + Add
          </button>
        </div>
        <input
          type="search"
          placeholder="Search conditions…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="mt-2 w-full rounded border border-ost-border bg-black/30 px-2 py-1.5 text-sm outline-none focus:border-blue-500"
        />
      </div>

      <ul className="flex-1 space-y-1 overflow-y-auto px-2 py-2">
        {filtered.map((c) => (
          <li key={c.id} className="flex gap-1">
            <button
              type="button"
              onClick={(e) => toggleSel(c.id, e.ctrlKey || e.metaKey)}
              className={`flex min-w-0 flex-1 items-center gap-2 rounded-md border px-2 py-1.5 text-left text-sm transition ${
                selected.includes(c.id)
                  ? 'border-blue-500 bg-blue-600/20'
                  : 'border-ost-border/60 bg-black/20 hover:bg-white/5'
              }`}
            >
              <span
                className="h-4 w-4 shrink-0 rounded-sm border border-white/20"
                style={{
                  background: c.color,
                  borderStyle:
                    linePatternToDashArray(c.linePattern) ? 'dashed' : 'solid',
                }}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{c.name}</div>
                <div className="text-[10px] uppercase text-ost-muted">
                  {KIND_LABEL[c.resultKind]} · {c.strokeWidth}px
                </div>
              </div>
            </button>
            <button
              type="button"
              title="Edit condition"
              onClick={(e) => {
                e.stopPropagation();
                setEditingConditionId(c.id);
              }}
              className="shrink-0 rounded-md border border-transparent px-2 py-1.5 text-ost-muted hover:border-ost-border hover:bg-white/10 hover:text-white"
            >
              ✎
            </button>
          </li>
        ))}
      </ul>

      <TotalsMini />

      <ConditionEditorModal
        conditionId={editingConditionId}
        onClose={() => setEditingConditionId(null)}
      />
    </aside>
  );
}

function TotalsMini() {
  const conditions = useProjectStore((s) => s.conditions);
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((x) => x + 1), 1600);
    return () => clearInterval(t);
  }, []);
  const rows = useMemo(() => {
    const fn = (
      window as unknown as { __takeoffExport?: () => { condition: string; quantity: string; unit: string }[] }
    ).__takeoffExport;
    if (!fn) return [];
    return fn();
  }, [conditions]);

  const byCond = useMemo(() => {
    const m = new Map<string, { qty: number; unit: string }>();
    for (const r of rows) {
      const k = r.condition;
      const q = parseFloat(r.quantity);
      if (!Number.isFinite(q)) continue;
      const cur = m.get(k) || { qty: 0, unit: r.unit };
      cur.qty += q;
      cur.unit = r.unit;
      m.set(k, cur);
    }
    return m;
  }, [rows]);

  return (
    <div className="border-t border-ost-border p-2">
      <div className="text-xs font-semibold uppercase text-ost-muted">
        Live totals (page)
      </div>
      <div className="mt-1 max-h-28 overflow-y-auto text-xs">
        {byCond.size === 0 ? (
          <span className="text-ost-muted">Draw or run Boost</span>
        ) : (
          [...byCond.entries()].map(([name, v]) => (
            <div key={name} className="flex justify-between gap-2 py-0.5">
              <span className="truncate text-ost-muted">{name}</span>
              <span className="shrink-0 font-mono text-blue-300">
                {v.qty.toFixed(1)} {v.unit}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
