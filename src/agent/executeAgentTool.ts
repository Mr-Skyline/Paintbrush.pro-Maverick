import { getAgentHostHandlers } from '@/agent/agentHost';
import { useNavigationStore } from '@/store/navigationStore';
import { useProjectStore } from '@/store/projectStore';
import type { Condition, LinePattern, ResultKind, TakeoffTool } from '@/types';
import { applyBoostReviewApproveAll } from '@/utils/boostReviewApply';
import { fabric } from 'fabric';

const RESULT_KINDS: ResultKind[] = [
  'linear',
  'area_gross',
  'area_net',
  'count',
  'assembly',
];
const LINE_PATTERNS: LinePattern[] = ['solid', 'dashed', 'dotted', 'dashdot'];
const TAKEOFF_TOOLS: TakeoffTool[] = [
  'select',
  'pan',
  'ai_scope',
  'line',
  'polyline',
  'polygon',
  'arc',
  'count',
  'measure',
  'text',
];

function parseArgs(raw: unknown): Record<string, unknown> {
  if (raw == null) return {};
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return {};
    }
  }
  if (typeof raw === 'object') return raw as Record<string, unknown>;
  return {};
}

export async function executeAgentTool(
  name: string,
  argsRaw: unknown
): Promise<string> {
  const args = parseArgs(argsRaw);
  try {
    switch (name) {
      case 'boost_run': {
        const scope = args.scope === 'all' ? 'all' : 'page';
        const h = getAgentHostHandlers().runBoost;
        if (!h) {
          return JSON.stringify({
            ok: false,
            error: 'Boost runner not available (open a project with a PDF).',
          });
        }
        const r = await h(scope);
        return JSON.stringify(r);
      }
      case 'boost_apply_review': {
        const r = applyBoostReviewApproveAll();
        return JSON.stringify(r);
      }
      case 'boost_review_add_conditions_only': {
        const st = useProjectStore.getState();
        const rev = st.boostReview;
        if (!rev) {
          return JSON.stringify({
            ok: false,
            error: 'No Boost review open.',
          });
        }
        st.applyBoostConditions(rev.suggestedConditions);
        return JSON.stringify({ ok: true });
      }
      case 'boost_dismiss_review': {
        const st = useProjectStore.getState();
        st.setBoostReview(null);
        st.setReviewOpen(false);
        return JSON.stringify({ ok: true });
      }
      case 'open_boost_dialog': {
        getAgentHostHandlers().openBoostDialog?.();
        return JSON.stringify({ ok: true });
      }
      case 'condition_add': {
        const nm = String(args.name ?? '').trim();
        const rk = args.result_kind as string;
        if (!nm || !RESULT_KINDS.includes(rk as ResultKind)) {
          return JSON.stringify({
            ok: false,
            error: 'name and valid result_kind required',
          });
        }
        const id = useProjectStore.getState().addCondition({
          name: nm,
          resultKind: rk as ResultKind,
          color:
            typeof args.color === 'string' ? args.color : undefined,
          linePattern: LINE_PATTERNS.includes(args.line_pattern as LinePattern)
            ? (args.line_pattern as LinePattern)
            : undefined,
          strokeWidth:
            typeof args.stroke_width === 'number'
              ? args.stroke_width
              : undefined,
          fillOpacity:
            typeof args.fill_opacity === 'number'
              ? args.fill_opacity
              : undefined,
        });
        return JSON.stringify({ ok: true, condition_id: id });
      }
      case 'condition_update': {
        const cid = String(args.condition_id ?? '');
        if (!cid) {
          return JSON.stringify({ ok: false, error: 'condition_id required' });
        }
        const patch: Partial<Omit<Condition, 'id'>> = {};
        if (typeof args.name === 'string') patch.name = args.name;
        if (typeof args.color === 'string') patch.color = args.color;
        if (
          typeof args.result_kind === 'string' &&
          RESULT_KINDS.includes(args.result_kind as ResultKind)
        ) {
          patch.resultKind = args.result_kind as ResultKind;
        }
        if (
          typeof args.line_pattern === 'string' &&
          LINE_PATTERNS.includes(args.line_pattern as LinePattern)
        ) {
          patch.linePattern = args.line_pattern as LinePattern;
        }
        if (typeof args.stroke_width === 'number') {
          patch.strokeWidth = args.stroke_width;
        }
        if (typeof args.fill_opacity === 'number') {
          patch.fillOpacity = args.fill_opacity;
        }
        const am = args.apply_to_marks;
        const opts =
          am === 'page'
            ? { applyToMarks: 'page' as const }
            : am === 'selection'
              ? { applyToMarks: 'selection' as const }
              : undefined;
        useProjectStore.getState().updateCondition(cid, patch, opts);
        return JSON.stringify({ ok: true });
      }
      case 'condition_remove': {
        const cid = String(args.condition_id ?? '');
        if (!cid) {
          return JSON.stringify({ ok: false, error: 'condition_id required' });
        }
        useProjectStore.getState().removeCondition(cid);
        return JSON.stringify({ ok: true });
      }
      case 'condition_select': {
        const ids = Array.isArray(args.condition_ids)
          ? (args.condition_ids as unknown[]).map((x) => String(x))
          : [];
        useProjectStore.getState().setSelectedConditions(ids);
        return JSON.stringify({ ok: true, selected: ids });
      }
      case 'set_current_page': {
        const p =
          typeof args.page === 'number' ? args.page : parseInt(String(args.page), 10);
        if (!Number.isFinite(p)) {
          return JSON.stringify({ ok: false, error: 'page must be a number' });
        }
        useProjectStore.getState().setPage(p);
        return JSON.stringify({ ok: true, page: p });
      }
      case 'set_takeoff_tool': {
        const t = String(args.tool ?? '');
        if (!TAKEOFF_TOOLS.includes(t as TakeoffTool)) {
          return JSON.stringify({ ok: false, error: `invalid tool: ${t}` });
        }
        useProjectStore.getState().setTool(t as TakeoffTool);
        return JSON.stringify({ ok: true, tool: t });
      }
      case 'set_pixels_per_foot': {
        const v =
          typeof args.value === 'number'
            ? args.value
            : parseFloat(String(args.value));
        if (!Number.isFinite(v) || v <= 0) {
          return JSON.stringify({ ok: false, error: 'value must be > 0' });
        }
        useProjectStore.getState().setPixelsPerFoot(v);
        return JSON.stringify({ ok: true });
      }
      case 'set_condition_search': {
        useProjectStore
          .getState()
          .setConditionSearch(String(args.query ?? ''));
        return JSON.stringify({ ok: true });
      }
      case 'set_active_document': {
        const did = String(args.document_id ?? '');
        if (!did) {
          return JSON.stringify({ ok: false, error: 'document_id required' });
        }
        const docs = useProjectStore.getState().documents;
        if (!docs.some((d) => d.id === did)) {
          return JSON.stringify({
            ok: false,
            error: `Unknown document_id. Options: ${docs.map((d) => d.id).join(', ')}`,
          });
        }
        useProjectStore.getState().setActiveDocument(did);
        return JSON.stringify({ ok: true });
      }
      case 'canvas_undo': {
        (window as unknown as { __takeoffUndo?: () => void }).__takeoffUndo?.();
        return JSON.stringify({ ok: true });
      }
      case 'canvas_redo': {
        (window as unknown as { __takeoffRedo?: () => void }).__takeoffRedo?.();
        return JSON.stringify({ ok: true });
      }
      case 'canvas_delete_selected': {
        const canvas = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
          .__takeoffCanvas;
        if (!canvas) {
          return JSON.stringify({ ok: false, error: 'No canvas' });
        }
        const active = canvas.getActiveObjects();
        if (!active.length) {
          return JSON.stringify({ ok: false, error: 'Nothing selected' });
        }
        const n = active.length;
        active.forEach((o) => canvas.remove(o));
        canvas.discardActiveObject();
        canvas.requestRenderAll();
        (
          window as unknown as { __takeoffPushUndoSnapshot?: () => void }
        ).__takeoffPushUndoSnapshot?.();
        return JSON.stringify({ ok: true, removed: n });
      }
      case 'canvas_clear_ai_focus': {
        (
          window as unknown as { __takeoffClearAiFocus?: () => void }
        ).__takeoffClearAiFocus?.();
        return JSON.stringify({ ok: true });
      }
      case 'highlight_mark': {
        const nid = String(args.mark_nid ?? '');
        if (!nid) {
          return JSON.stringify({ ok: false, error: 'mark_nid required' });
        }
        useProjectStore.getState().setHighlightNid(nid);
        return JSON.stringify({ ok: true });
      }
      case 'toggle_left_sidebar': {
        useProjectStore.getState().toggleLeft();
        return JSON.stringify({ ok: true });
      }
      case 'toggle_right_sidebar': {
        useProjectStore.getState().toggleRight();
        return JSON.stringify({ ok: true });
      }
      case 'set_boost_review_panel_open': {
        const open = Boolean(args.open);
        const st = useProjectStore.getState();
        if (open && !st.boostReview) {
          return JSON.stringify({
            ok: false,
            error: 'No Boost review loaded. Run boost_run first.',
          });
        }
        st.setReviewOpen(open);
        return JSON.stringify({ ok: true, open: st.reviewOpen });
      }
      case 'project_save_local': {
        const h = getAgentHostHandlers().saveProject;
        if (!h) {
          return JSON.stringify({ ok: false, error: 'Save not available' });
        }
        return JSON.stringify(await h());
      }
      case 'navigate_to_projects_screen': {
        const nav = getAgentHostHandlers().goToProjects;
        if (nav) nav();
        else useNavigationStore.getState().goToProjects();
        return JSON.stringify({ ok: true });
      }
      default:
        return JSON.stringify({
          ok: false,
          error: `Unknown tool: ${name}`,
        });
    }
  } catch (e) {
    return JSON.stringify({
      ok: false,
      error: String(e instanceof Error ? e.message : e),
    });
  }
}
