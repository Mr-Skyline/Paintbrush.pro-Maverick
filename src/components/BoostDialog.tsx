import { useProjectStore } from '@/store/projectStore';

export function BoostDialog({
  open,
  onClose,
  onRun,
}: {
  open: boolean;
  onClose: () => void;
  onRun: (scope: 'page' | 'all') => void;
}) {
  const boostPrefs = useProjectStore((s) => s.boostPrefs);
  const setBoostPrefs = useProjectStore((s) => s.setBoostPrefs);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-md rounded-xl border border-ost-border bg-ost-panel p-6 shadow-2xl">
        <h2 className="text-lg font-semibold text-white">Takeoff Boost</h2>
        <p className="mt-1 text-sm text-ost-muted">
          Uses native PDF text + heuristics (full vector wall detect is
          iterative). On <strong className="text-slate-300">this page</strong>,
          if you drew the purple <strong className="text-violet-300">AI box</strong>{' '}
          on the sheet, Boost places wall/door/window/ceiling candidates{' '}
          <em>inside</em> that region only.
        </p>

        <label className="mt-4 block text-sm">
          <span className="text-ost-muted">Default wall height (ft)</span>
          <input
            type="number"
            step={0.1}
            className="mt-1 w-full rounded border border-ost-border bg-black/40 px-2 py-2"
            value={boostPrefs.defaultWallHeightFt}
            onChange={(e) =>
              setBoostPrefs({
                defaultWallHeightFt: parseFloat(e.target.value) || 8,
              })
            }
          />
        </label>

        <label className="mt-3 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={boostPrefs.preferSplitCeilings}
            onChange={(e) =>
              setBoostPrefs({ preferSplitCeilings: e.target.checked })
            }
          />
          Prefer split ACT vs GWB ceilings
        </label>
        <label className="mt-2 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={boostPrefs.paintBothSidesInterior}
            onChange={(e) =>
              setBoostPrefs({ paintBothSidesInterior: e.target.checked })
            }
          />
          Interior paint both sides (narrative for Grok / reports)
        </label>

        <div className="mt-6 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              onRun('page');
              onClose();
            }}
            className="flex-1 rounded-lg bg-emerald-600 py-2 text-sm font-semibold hover:bg-emerald-500"
          >
            Run — this page
          </button>
          <button
            type="button"
            onClick={() => {
              onRun('all');
              onClose();
            }}
            className="flex-1 rounded-lg border border-ost-border py-2 text-sm hover:bg-white/5"
          >
            All pages (stub)
          </button>
          <button
            type="button"
            onClick={onClose}
            className="w-full rounded-lg py-2 text-sm text-ost-muted hover:bg-white/5"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
