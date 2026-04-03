import { useProjectStore } from '@/store/projectStore';
import { buildAiFocusContextForGrok } from '@/utils/aiFocusContext';
import { fabric } from 'fabric';

/** Compact state Grok sees each agent step (refreshed after tools). */
export function buildAgentSnapshot() {
  const st = useProjectStore.getState();
  const rows =
    (window as unknown as { __takeoffExport?: () => unknown[] }).__takeoffExport?.() ??
    [];
  const canvas = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
    .__takeoffCanvas;
  const aiFocusRegion = buildAiFocusContextForGrok(canvas, st.currentPage);
  return {
    projectName: st.projectName,
    projectId: st.projectId,
    documents: st.documents.map((d) => ({
      id: d.id,
      name: d.name,
      pageCount: d.pageCount,
    })),
    activeDocumentId: st.activeDocumentId,
    currentPage: st.currentPage,
    totalPages: st.totalPages,
    takeoffTool: st.tool,
    pixelsPerFoot: st.pixelsPerFoot,
    conditionSearch: st.conditionSearch,
    selectedConditionIds: st.selectedConditionIds,
    conditions: st.conditions,
    boostReviewOpen: st.reviewOpen,
    boostHeadline: st.boostReview?.headline ?? null,
    boostFindingCount: st.boostReview?.findings?.length ?? 0,
    exportSample: rows.slice(0, 24),
    aiFocusRegion,
  };
}
