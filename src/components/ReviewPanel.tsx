import { recordAgentTrace } from '@/lib/agentTrace';
import { useProjectStore } from '@/store/projectStore';
import { applyBoostReviewApproveAll } from '@/utils/boostReviewApply';

export function ReviewPanel() {
  const review = useProjectStore((s) => s.boostReview);
  const setReview = useProjectStore((s) => s.setBoostReview);
  const setReviewOpen = useProjectStore((s) => s.setReviewOpen);
  const reviewOpen = useProjectStore((s) => s.reviewOpen);
  const applyBoostConditions = useProjectStore((s) => s.applyBoostConditions);

  if (!review || !reviewOpen) return null;

  const findingsCount = review.findings.length;
  const suggestedConditionsCount = review.suggestedConditions.length;

  const approveAll = () => {
    const r = applyBoostReviewApproveAll();
    recordAgentTrace('outcome', 'review_approve_all', {
      result: r.ok ? 'ok' : 'error',
      context: {
        findingsCount,
        suggestedConditionsCount,
        applied: r.applied,
        markersBefore: r.markersBefore,
        markersAfter: r.markersAfter,
        ...(r.error ? { error: r.error } : {}),
      },
    });
    if (!r.ok) alert(r.error ?? 'Could not apply Boost review.');
  };

  return (
    <div className="fixed inset-x-0 bottom-0 z-50 max-h-[45vh] overflow-hidden border-t border-violet-500/40 bg-ost-panel shadow-2xl">
      <div className="flex items-start justify-between gap-4 border-b border-ost-border p-4">
        <div>
          <h3 className="text-lg font-semibold text-violet-200">
            Takeoff Boost — Review
          </h3>
          <p className="mt-1 text-sm text-ost-muted">{review.headline}</p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={approveAll}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium hover:bg-violet-500"
          >
            Approve &amp; draw all
          </button>
          <button
            type="button"
            onClick={() => {
              recordAgentTrace('decision', 'review_add_conditions_only', {
                result: 'ok',
                context: { findingsCount, suggestedConditionsCount },
              });
              applyBoostConditions(review.suggestedConditions);
            }}
            className="rounded-lg border border-ost-border px-3 py-2 text-sm hover:bg-white/5"
          >
            Add conditions only
          </button>
          <button
            type="button"
            onClick={() => {
              recordAgentTrace('decision', 'review_dismiss', {
                result: 'ok',
                context: { findingsCount, suggestedConditionsCount },
              });
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
              className="rounded border border-ost-border bg-black/20 p-2 text-xs"
            >
              <span className="font-medium text-slate-200">{f.kind}</span>:{' '}
              {f.description}
              <div className="mt-1 text-ost-muted">
                → {f.conditionName} ({Math.round(f.confidence * 100)}%)
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
