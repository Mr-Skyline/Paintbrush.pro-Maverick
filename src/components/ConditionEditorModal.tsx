import { useProjectStore } from '@/store/projectStore';
import type { LinePattern, ResultKind } from '@/types';
import { isAreaResultKind } from '@/utils/conditionStyle';
import { useEffect, useMemo, useState } from 'react';

const KIND_LABEL: Record<ResultKind, string> = {
  linear: 'Linear (LF)',
  area_gross: 'Area gross (SF)',
  area_net: 'Area net (SF)',
  count: 'Count',
  assembly: 'Assembly',
};

const PATTERN_LABEL: Record<LinePattern, string> = {
  solid: 'Solid',
  dashed: 'Dashed',
  dotted: 'Dotted',
  dashdot: 'Dash–dot',
};

type ApplyMode = 'none' | 'page' | 'selection';

export function ConditionEditorModal({
  conditionId,
  onClose,
}: {
  conditionId: string | null;
  onClose: () => void;
}) {
  const conditions = useProjectStore((s) => s.conditions);
  const updateCondition = useProjectStore((s) => s.updateCondition);

  const source = useMemo(
    () => conditions.find((c) => c.id === conditionId) ?? null,
    [conditions, conditionId]
  );

  const [name, setName] = useState('');
  const [color, setColor] = useState('#3b82f6');
  const [resultKind, setResultKind] = useState<ResultKind>('linear');
  const [linePattern, setLinePattern] = useState<LinePattern>('solid');
  const [strokeWidth, setStrokeWidth] = useState(2);
  const [fillOpacity, setFillOpacity] = useState(0.14);
  const [applyMode, setApplyMode] = useState<ApplyMode>('none');

  useEffect(() => {
    if (!source) return;
    setName(source.name);
    setColor(source.color);
    setResultKind(source.resultKind);
    setLinePattern(source.linePattern);
    setStrokeWidth(source.strokeWidth);
    setFillOpacity(source.fillOpacity);
    setApplyMode('none');
  }, [source]);

  if (!conditionId || !source) return null;

  const showFill = isAreaResultKind(resultKind);

  const save = () => {
    const applyToMarks =
      applyMode === 'none'
        ? undefined
        : applyMode === 'page'
          ? ('page' as const)
          : ('selection' as const);
    updateCondition(
      conditionId,
      {
        name: name.trim() || source.name,
        color,
        resultKind,
        linePattern,
        strokeWidth,
        fillOpacity,
      },
      { applyToMarks }
    );
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="cond-edit-title"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border border-ost-border bg-ost-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-ost-border px-4 py-3">
          <h2 id="cond-edit-title" className="text-sm font-semibold text-white">
            Edit condition
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded px-2 py-1 text-ost-muted hover:bg-white/10 hover:text-white"
          >
            ✕
          </button>
        </div>

        <div className="max-h-[70vh] space-y-3 overflow-y-auto p-4 text-sm">
          <label className="block">
            <span className="mb-1 block text-xs text-ost-muted">Name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded border border-ost-border bg-black/40 px-2 py-2 outline-none focus:border-blue-500"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs text-ost-muted">Result type</span>
            <select
              value={resultKind}
              onChange={(e) =>
                setResultKind(e.target.value as ResultKind)
              }
              className="w-full rounded border border-ost-border bg-black/40 px-2 py-2"
            >
              {(Object.keys(KIND_LABEL) as ResultKind[]).map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k]}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-3">
            <span className="w-24 shrink-0 text-xs text-ost-muted">Color</span>
            <input
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              className="h-9 w-14 cursor-pointer rounded border border-ost-border bg-transparent"
            />
            <input
              value={color}
              onChange={(e) => setColor(e.target.value)}
              className="min-w-0 flex-1 rounded border border-ost-border bg-black/40 px-2 py-1.5 font-mono text-xs"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs text-ost-muted">Line style</span>
            <select
              value={linePattern}
              onChange={(e) =>
                setLinePattern(e.target.value as LinePattern)
              }
              className="w-full rounded border border-ost-border bg-black/40 px-2 py-2"
            >
              {(Object.keys(PATTERN_LABEL) as LinePattern[]).map((p) => (
                <option key={p} value={p}>
                  {PATTERN_LABEL[p]}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs text-ost-muted">
              Line thickness ({strokeWidth}px)
            </span>
            <input
              type="range"
              min={1}
              max={16}
              value={strokeWidth}
              onChange={(e) => setStrokeWidth(Number(e.target.value))}
              className="w-full"
            />
          </label>

          {showFill && (
            <label className="block">
              <span className="mb-1 block text-xs text-ost-muted">
                Area fill strength ({Math.round(fillOpacity * 100)}%)
              </span>
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round(fillOpacity * 100)}
                onChange={(e) =>
                  setFillOpacity(Number(e.target.value) / 100)
                }
                className="w-full"
              />
            </label>
          )}

          <fieldset className="rounded border border-ost-border/80 p-3">
            <legend className="px-1 text-xs text-ost-muted">
              Existing marks on canvas
            </legend>
            <div className="space-y-2 text-xs">
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="applyMode"
                  checked={applyMode === 'none'}
                  onChange={() => setApplyMode('none')}
                />
                <span>Keep as-is (new marks use these settings)</span>
              </label>
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="applyMode"
                  checked={applyMode === 'page'}
                  onChange={() => setApplyMode('page')}
                />
                <span>Restyle all marks with this condition on this sheet</span>
              </label>
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="applyMode"
                  checked={applyMode === 'selection'}
                  onChange={() => setApplyMode('selection')}
                />
                <span>Restyle selected marks only</span>
              </label>
            </div>
          </fieldset>
        </div>

        <div className="flex justify-end gap-2 border-t border-ost-border px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-ost-border px-3 py-2 text-sm hover:bg-white/5"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={save}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
