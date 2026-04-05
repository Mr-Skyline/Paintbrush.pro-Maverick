import { useProjectStore } from '@/store/projectStore';
import type { BoostFinding } from '@/types';
import { recordAgentTrace } from '@/lib/agentTrace';
import {
  applyConditionVisualToFabricObject,
  hexAlpha,
  linePatternToDashArray,
} from '@/utils/conditionStyle';
import { fabric } from 'fabric';

function applyFinding(
  finding: BoostFinding,
  conditionId: string,
  color: string
) {
  const c = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
    .__takeoffCanvas;
  if (!c) return;
  let obj: fabric.Object | null = null;
  const g = finding.geometry;
  if (g.type === 'line') {
    obj = new fabric.Line([g.x1, g.y1, g.x2, g.y2], {});
  } else if (g.type === 'polygon') {
    obj = new fabric.Polygon(g.points, { objectCaching: false });
  } else if (g.type === 'rect') {
    obj = new fabric.Rect({
      left: g.x,
      top: g.y,
      width: g.w,
      height: g.h,
      fill: 'transparent',
    });
  } else if (g.type === 'point') {
    obj = new fabric.Circle({
      left: g.x - 5,
      top: g.y - 5,
      radius: 5,
      originX: 'left',
      originY: 'top',
    });
  }
  if (!obj) return;
  const mark = obj as fabric.Object & {
    nid?: string;
    conditionIds?: string[];
    isBoost?: boolean;
  };
  const st = useProjectStore.getState();
  const cond = st.conditions.find((x) => x.id === conditionId);
  if (cond) {
    mark.set({
      nid: `boost-${finding.id}`,
      conditionIds: [conditionId],
    });
    applyConditionVisualToFabricObject(mark, [conditionId], st.conditions);
  } else {
    mark.set({
      stroke: color,
      strokeWidth: 2,
      fill:
        finding.kind === 'ceiling_act' || finding.kind === 'ceiling_gwb'
          ? hexAlpha('#a855f7', 0.12)
          : 'transparent',
      strokeDashArray:
        finding.kind === 'wall' ? linePatternToDashArray('dashed') : undefined,
      nid: `boost-${finding.id}`,
      conditionIds: [conditionId],
    });
  }
  mark.isBoost = true;
  (obj as fabric.Object & { markType?: string }).markType =
    finding.kind === 'door' || finding.kind === 'window' ? 'count' : 'line';
  c.add(obj);
  c.renderAll();
}

function ensureCondition(name: string, fallbackColor: string) {
  const st = useProjectStore.getState();
  let cond = st.conditions.find((x) => x.name === name);
  if (!cond) {
    const id = st.addCondition({
      name,
      color: fallbackColor,
      resultKind:
        /door|window/i.test(name)
          ? 'count'
          : /ceiling|area/i.test(name)
            ? 'area_gross'
            : 'linear',
    });
    cond = useProjectStore.getState().conditions.find((x) => x.id === id);
  }
  return cond;
}

/** Same as Review panel "Approve & draw all". */
export function applyBoostReviewApproveAll(): {
  ok: boolean;
  error?: string;
  applied?: number;
} {
  const st = useProjectStore.getState();
  const review = st.boostReview;
  if (!review) {
    recordAgentTrace({
      category: 'outcome',
      event: 'review.approve_all_blocked',
      reason: 'No active review was open when approve all was requested.',
      result: 'error',
    });
    return {
      ok: false,
      error: 'No Boost review is open. Call boost_run first.',
    };
  }
  const c = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
    .__takeoffCanvas;
  if (!c) {
    recordAgentTrace({
      category: 'outcome',
      event: 'review.approve_all_blocked',
      reason: 'Canvas was not ready when approve all was requested.',
      result: 'error',
    });
    return { ok: false, error: 'Canvas not ready.' };
  }
  recordAgentTrace({
    category: 'decision',
    event: 'review.approve_all_requested',
    reason: 'User requested to apply all AI findings to the active sheet.',
    result: 'neutral',
    context: {
      findings: review.findings.length,
      suggestedConditions: review.suggestedConditions.length,
    },
  });
  st.applyBoostConditions(review.suggestedConditions);
  for (const f of review.findings) {
    const cond = ensureCondition(
      f.conditionName,
      f.kind === 'wall'
        ? '#22c55e'
        : f.kind.startsWith('ceiling')
          ? '#a855f7'
          : '#f97316'
    );
    if (cond) applyFinding(f, cond.id, cond.color);
  }
  const applied = review.findings.length;
  st.setBoostReview(null);
  st.setReviewOpen(false);
  const snap = (window as unknown as { __takeoffPushUndoSnapshot?: () => void })
    .__takeoffPushUndoSnapshot;
  snap?.();
  recordAgentTrace({
    category: 'outcome',
    event: 'review.approve_all_applied',
    reason: 'Applied all AI findings and suggested conditions to the canvas.',
    result: 'success',
    context: { applied },
  });
  return { ok: true, applied };
}
