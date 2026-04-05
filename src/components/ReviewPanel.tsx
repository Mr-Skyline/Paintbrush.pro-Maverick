import { useProjectStore } from '@/store/projectStore';
import { applyBoostReviewApproveAll } from '@/utils/boostReviewApply';

const FINDING_LABELS: Record<string, string> = {
  wall: 'Wall segment',
  ceiling_act: 'ACT ceiling',
  ceiling_gwb: 'GWB ceiling',
  door: 'Door',
  window: 'Window',
  room: 'Room',
  fixture: 'Fixture',
};

export function ReviewPanel() {
  const review = useProjectStore((s) => s.boostReview);
  const setReview = useProjectStore((s) => s.setBoostReview);
  const setReviewOpen = useProjectStore((s) => s.setReviewOpen);
  const reviewOpen = useProjectStore((s) => s.reviewOpen);
  const applyBoostConditions = useProjectStore((s) => s.applyBoostConditions);

  if (!review || !reviewOpen) return null;

  const approveAll = () => {
    const r = applyBoostReviewApproveAll();
    if (!r.ok) alert(r.error ?? 'Could not apply Boost review.');
  };

  return (
    <div className="fixed inset-x-0 bottom-0 z-50 max-h-[48vh] overflow-hidden border-t border-violet-500/40 bg-gradient-to-b from-[#151a26] to-[#111722] shadow-2xl">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-ost-border p-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-violet-300/90">
            AI findings
          </p>
          <h3 className="text-lg font-semibold text-violet-100">
            AI Takeoff Review
          </h3>
          <p className="mt-1 max-w-3xl text-sm text-ost-muted">{review.headline}</p>
          <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
            <span className="rounded-full border border-ost-border/80 bg-black/20 px-2 py-0.5 text-ost-muted">
              {review.findings.length} findings
            </span>
            <span className="rounded-full border border-ost-border/80 bg-black/20 px-2 py-0.5 text-ost-muted">
              {review.suggestedConditions.length} suggested conditions
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={approveAll}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white hover:bg-violet-500"
          >
            Approve + draw all marks
          </button>
          <button
            type="button"
            onClick={() => {
              applyBoostConditions(review.suggestedConditions);
            }}
            className="rounded-lg border border-ost-border px-3 py-2 text-sm hover:bg-white/5"
          >
            Add conditions only
          </button>
          <button
            type="button"
            onClick={() => {
              setReview(null);
              setReviewOpen(false);
            }}
            className="rounded-lg px-3 py-2 text-sm text-ost-muted hover:bg-white/5"
          >
            Dismiss
          </button>
        </div>
      </div>
      <div className="overflow-y-auto p-4 text-sm">
        <ul className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
          {review.findings.slice(0, 60).map((f) => (
            <li
              key={f.id}
              className="rounded-md border border-ost-border/80 bg-black/20 p-2 text-xs"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-slate-100">
                  {FINDING_LABELS[f.kind] ?? f.kind}
                </span>
                <span className="rounded-full border border-ost-border/80 px-1.5 py-0.5 text-[10px] text-ost-muted">
                  {Math.round(f.confidence * 100)}%
                </span>
              </div>
              <p className="mt-1 text-slate-300">{f.description}</p>
              <div className="mt-1 text-ost-muted">
                → Condition: {f.conditionName}
              </div>
            </li>
          ))}
        </ul>
        {review.findings.length > 60 && (
          <p className="mt-2 text-ost-muted">
            + {review.findings.length - 60} more (approve all to include)
          </p>
        )}
      </div>
    </div>
  );
}
