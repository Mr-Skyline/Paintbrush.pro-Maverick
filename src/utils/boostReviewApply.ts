import { recordAgentTrace } from '@/lib/agentTrace';
import { useProjectStore } from '@/store/projectStore';
import type { BoostFinding } from '@/types';
import {
  applyConditionVisualToFabricObject,
  hexAlpha,
  linePatternToDashArray,
} from '@/utils/conditionStyle';
import { fabric } from 'fabric';

function countBoostMarkersOnCanvas(c: fabric.Canvas): number {
  return c.getObjects().filter(
    (o) => (o as fabric.Object & { isBoost?: boolean }).isBoost
  ).length;
}

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

export type BoostReviewApplyMetrics = {
  findingsBefore: number;
  conditionsBefore: number;
  conditionsAfter: number;
  conditionsAdded: number;
  canvasObjectCountBefore: number;
  canvasObjectCountAfter: number;
  canvasObjectsAdded: number;
};

export type ApplyBoostReviewApproveAllResult = {
  ok: boolean;
  error?: string;
  applied?: number;
  metrics?: BoostReviewApplyMetrics;
  /** @deprecated Prefer metrics.* — kept for backward compatibility with serialized tool results. */
  markersBefore?: number;
  /** @deprecated Prefer metrics.* */
  markersAfter?: number;
  /** @deprecated Prefer metrics.canvasObjectsAdded */
  appliedFindings?: number;
  /** @deprecated Prefer metrics.conditionsAdded */
  conditionsAdded?: number;
  /** @deprecated Prefer metrics.canvasObjectCountBefore */
  canvasObjectCountBefore?: number;
  /** @deprecated Prefer metrics.canvasObjectCountAfter */
  canvasObjectCountAfter?: number;
};

function getTakeoffCanvas(): fabric.Canvas | null {
  const c = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
    .__takeoffCanvas;
  return c ?? null;
}

/**
 * Pre-apply snapshot of store and canvas for the current Boost review.
 * `conditionsAfter` / `canvasObjectCountAfter` match `*Before` and added counts are zero.
 */
export function previewBoostReviewMetrics():
  | { ok: true; metrics: BoostReviewApplyMetrics }
  | { ok: false; error: string } {
  const st = useProjectStore.getState();
  const review = st.boostReview;
  if (!review) {
    return {
      ok: false,
      error: 'No Boost review is open. Call boost_run first.',
    };
  }
  const c = getTakeoffCanvas();
  if (!c) {
    return { ok: false, error: 'Canvas not ready.' };
  }
  const findingsBefore = review.findings.length;
  const conditionsBefore = st.conditions.length;
  const canvasObjectCountBefore = c.getObjects().length;
  return {
    ok: true,
    metrics: {
      findingsBefore,
      conditionsBefore,
      conditionsAfter: conditionsBefore,
      conditionsAdded: 0,
      canvasObjectCountBefore,
      canvasObjectCountAfter: canvasObjectCountBefore,
      canvasObjectsAdded: 0,
    },
  };
}

/** Clear Boost review state and close the review panel (no apply). */
export function dismissBoostReview(): { ok: true } {
  const st = useProjectStore.getState();
  st.setBoostReview(null);
  st.setReviewOpen(false);
  return { ok: true };
}

/** Same as Review panel "Approve & draw all". */
export function applyBoostReviewApproveAll(): ApplyBoostReviewApproveAllResult {
  const st = useProjectStore.getState();
  const review = st.boostReview;
  if (!review) {
    const error = 'No Boost review is open. Call boost_run first.';
    recordAgentTrace({
      event: 'review_approve_all',
      category: 'decision',
      result: 'error',
      context: {
        findingsCountBefore: 0,
        findingsCountAfter: 0,
        suggestedConditionsCountBefore: 0,
        suggestedConditionsCountAfter: 0,
        appliedCount: 0,
        appliedFindings: 0,
        error,
      },
    });
    return {
      ok: false,
      error,
    };
  }
  const findingsBefore = review.findings.length;
  const suggestedConditionsCount = review.suggestedConditions.length;
  const c = getTakeoffCanvas();
  if (!c) {
    const error = 'Canvas not ready.';
    recordAgentTrace({
      event: 'review_approve_all',
      category: 'decision',
      result: 'error',
      context: {
        findingsCountBefore: findingsBefore,
        findingsCountAfter: findingsBefore,
        suggestedConditionsCountBefore: suggestedConditionsCount,
        suggestedConditionsCountAfter: suggestedConditionsCount,
        appliedCount: 0,
        appliedFindings: 0,
        error,
      },
    });
    return { ok: false, error };
  }
  const conditionsBefore = st.conditions.length;
  const canvasObjectCountBefore = c.getObjects().length;
  const markersBefore = countBoostMarkersOnCanvas(c);
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
  const appliedFindings = countBoostMarkersOnCanvas(c) - markersBefore;
  const markersAfter = countBoostMarkersOnCanvas(c);
  const canvasObjectCountAfter = c.getObjects().length;
  const conditionsAfter = useProjectStore.getState().conditions.length;
  const conditionsAdded = conditionsAfter - conditionsBefore;
  const canvasObjectsAdded = canvasObjectCountAfter - canvasObjectCountBefore;
  const metrics: BoostReviewApplyMetrics = {
    findingsBefore,
    conditionsBefore,
    conditionsAfter,
    conditionsAdded,
    canvasObjectCountBefore,
    canvasObjectCountAfter,
    canvasObjectsAdded,
  };
  st.setBoostReview(null);
  st.setReviewOpen(false);
  const snap = (window as unknown as { __takeoffPushUndoSnapshot?: () => void })
    .__takeoffPushUndoSnapshot;
  snap?.();
    recordAgentTrace({
      event: 'review_approve_all',
      category: 'decision',
      result: 'success',
    context: {
      findingsCountBefore: findingsBefore,
      findingsCountAfter: 0,
      suggestedConditionsCountBefore: suggestedConditionsCount,
      suggestedConditionsCountAfter: 0,
      appliedCount: appliedFindings,
      appliedFindings,
      appliedFindingsAttempted: findingsBefore,
      conditionsAdded,
      conditionsAddedAttempted: suggestedConditionsCount,
      canvasObjectCountBefore,
      canvasObjectCountAfter,
      markersBefore,
      markersAfter,
      metrics,
    },
  });
  return {
    ok: true,
    applied: review.findings.length,
    metrics,
    appliedFindings,
    conditionsAdded,
    canvasObjectCountBefore,
    canvasObjectCountAfter,
    markersBefore,
    markersAfter,
  };
}
