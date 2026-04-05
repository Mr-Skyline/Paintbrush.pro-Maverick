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

/** Same as Review panel "Approve & draw all". */
export function applyBoostReviewApproveAll(): {
  ok: boolean;
  error?: string;
  applied?: number;
  markersBefore?: number;
  markersAfter?: number;
  appliedFindings?: number;
  conditionsAdded?: number;
  canvasObjectCountBefore?: number;
  canvasObjectCountAfter?: number;
} {
  const st = useProjectStore.getState();
  const review = st.boostReview;
  if (!review) {
    const error = 'No Boost review is open. Call boost_run first.';
    recordAgentTrace({
      event: 'review_approve_all',
      category: 'review',
      result: 'failure',
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
  const findingsCount = review.findings.length;
  const suggestedConditionsCount = review.suggestedConditions.length;
  const c = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
    .__takeoffCanvas;
  if (!c) {
    const error = 'Canvas not ready.';
    recordAgentTrace({
      event: 'review_approve_all',
      category: 'review',
      result: 'failure',
      context: {
        findingsCountBefore: findingsCount,
        findingsCountAfter: findingsCount,
        suggestedConditionsCountBefore: suggestedConditionsCount,
        suggestedConditionsCountAfter: suggestedConditionsCount,
        appliedCount: 0,
        appliedFindings: 0,
        error,
      },
    });
    return { ok: false, error };
  }
  const canvasObjectCountBefore = c.getObjects().length;
  const markersBefore = countBoostMarkersOnCanvas(c);
  st.applyBoostConditions(review.suggestedConditions);
  const conditionsAdded = review.suggestedConditions.length;
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
  st.setBoostReview(null);
  st.setReviewOpen(false);
  const snap = (window as unknown as { __takeoffPushUndoSnapshot?: () => void })
    .__takeoffPushUndoSnapshot;
  snap?.();
  recordAgentTrace({
    event: 'review_approve_all',
    category: 'review',
    result: 'success',
    context: {
      findingsCountBefore: findingsCount,
      findingsCountAfter: 0,
      suggestedConditionsCountBefore: suggestedConditionsCount,
      suggestedConditionsCountAfter: 0,
      appliedCount: appliedFindings,
      appliedFindings,
      appliedFindingsAttempted: findingsCount,
      conditionsAdded,
      conditionsAddedAttempted: suggestedConditionsCount,
      canvasObjectCountBefore,
      canvasObjectCountAfter,
      markersBefore,
      markersAfter,
    },
  });
  return {
    ok: true,
    applied: review.findings.length,
    appliedFindings,
    conditionsAdded,
    canvasObjectCountBefore,
    canvasObjectCountAfter,
    markersBefore,
    markersAfter,
  };
}
