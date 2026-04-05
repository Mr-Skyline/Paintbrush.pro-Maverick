import { useProjectStore } from '@/store/projectStore';
import { recordAgentTrace } from '@/lib/agentTrace';
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
    recordAgentTrace({
      category: 'action',
      event: 'review.approve_all.click',
      reason: 'Operator approved all AI findings for this review batch.',
      context: {
        findings: review.findings.length,
        suggestedConditions: review.suggestedConditions.length,
      },
    });
    const r = applyBoostReviewApproveAll();
    if (!r.ok) {
      recordAgentTrace({
        category: 'outcome',
        event: 'review.approve_all.result',
        result: 'error',
        reason: r.error ?? 'Approve-all failed in Boost review.',
      });
      alert(r.error ?? 'Could not apply Boost review.');
      return;
    }
    recordAgentTrace({
      category: 'outcome',
      event: 'review.approve_all.result',
      result: 'success',
      reason: 'Boost review findings were applied to canvas.',
      context: {
        applied: r.applied ?? review.findings.length,
      },
    });
  };

  return (
    <div className="fixed inset-x-0 bottom-0 z-50 max-h-[42vh] overflow-hidden border-t border-violet-500/40 bg-gradient-to-b from-[#151a26] to-[#111722] shadow-2xl">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-ost-border p-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-violet-300/90">
            AI findings
          </p>
          <h3 className="text-base font-semibold text-violet-100">
            AI Takeoff Review
          </h3>
          <p className="mt-1 max-w-3xl text-xs text-ost-muted">{review.headline}</p>
          <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
            <span className="rounded-full border border-ost-border/80 bg-black/20 px-2 py-0.5 text-ost-muted">
              {review.findings.length} findings
            </span>
            <span className="rounded-full border border-ost-border/80 bg-black/20 px-2 py-0.5 text-ost-muted">
              {review.suggestedConditions.length} suggested conditions
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={approveAll}
            className="rounded-md bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-violet-500"
          >
            Approve + draw all marks
          </button>
          <button
            type="button"
            onClick={() => {
              recordAgentTrace({
                category: 'action',
                event: 'review.add_conditions_only.click',
                reason:
                  'Operator accepted suggested conditions without drawing all marks.',
                context: {
                  suggestedConditions: review.suggestedConditions.length,
                },
              });
              applyBoostConditions(review.suggestedConditions);
              recordAgentTrace({
                category: 'outcome',
                event: 'review.add_conditions_only.result',
                result: 'success',
                context: {
                  suggestedConditions: review.suggestedConditions.length,
                },
              });
            }}
            className="rounded-md border border-ost-border px-2.5 py-1.5 text-xs hover:bg-white/5"
          >
            Add conditions only
          </button>
          <button
            type="button"
            onClick={() => {
              recordAgentTrace({
                category: 'action',
                event: 'review.dismiss.click',
                reason: 'Operator dismissed AI review without full apply.',
                context: {
                  findings: review.findings.length,
                },
              });
              setReview(null);
              setReviewOpen(false);
            }}
            className="rounded-md px-2.5 py-1.5 text-xs text-ost-muted hover:bg-white/5"
          >
            Dismiss
          </button>
        </div>
      </div>
      <div className="overflow-y-auto p-3 text-sm">
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
