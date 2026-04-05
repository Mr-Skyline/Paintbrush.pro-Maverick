import { useTakeoffSocket } from '@/hooks/useSocket';
import { useProjectStore } from '@/store/projectStore';
import {
  FABRIC_KEYS,
  rowsFromCanvasPage,
} from '@/utils/exportTakeoff';
import {
  fabricLineLength,
  feetFromPixels,
  polygonAreaPx,
  sqFeetFromPixels,
} from '@/utils/measurements';
import { arcPathFromThreePoints } from '@/utils/geometry';
import { applyConditionVisualToFabricObject } from '@/utils/conditionStyle';
import { fabric } from 'fabric';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import { useEffect, useRef, useState } from 'react';
import { openPdfFromArrayBuffer } from '@/utils/openPdfFromArrayBuffer';

function nid() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
}

type DrawState =
  | { mode: 'line'; a: { x: number; y: number } }
  | { mode: 'polyline'; points: { x: number; y: number }[] }
  | { mode: 'polygon'; points: { x: number; y: number }[] }
  | { mode: 'arc'; pts: { x: number; y: number }[] }
  | { mode: 'measure'; a: { x: number; y: number } }
  | null;

function applyStyleToObject(
  obj: fabric.Object,
  conditions: ReturnType<typeof useProjectStore.getState>['conditions'],
  selectedIds: string[]
): boolean {
  const ids = selectedIds.filter((id) => conditions.some((c) => c.id === id));
  if (!ids.length) return false;
  applyConditionVisualToFabricObject(obj, ids, conditions);
  const mark = obj as fabric.Object & {
    nid?: string;
    conditionIds?: string[];
    isBoost?: boolean;
  };
  mark.set({
    nid: nid(),
    conditionIds: [...ids],
  });
  mark.isBoost = false;
  return true;
}

export function CanvasWorkspace({ pdfData }: { pdfData: ArrayBuffer | null }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const pdfCanvasRef = useRef<HTMLCanvasElement>(null);
  const fabricElRef = useRef<HTMLCanvasElement>(null);
  const fabricRef = useRef<fabric.Canvas | null>(null);
  const pdfDocRef = useRef<PDFDocumentProxy | null>(null);
  const drawRef = useRef<DrawState>(null);
  const undoRef = useRef<string[]>([]);
  const redoRef = useRef<string[]>([]);
  const suppressRef = useRef({ emit: false, undo: false });
  const mySidRef = useRef<string | null>(null);
  const socketRef = useTakeoffSocket(true);
  const [pdfDocGeneration, setPdfDocGeneration] = useState(0);
  const aiScopeDragRef = useRef<{ x: number; y: number } | null>(null);
  const aiScopePreviewRef = useRef<fabric.Rect | null>(null);

  const currentPage = useProjectStore((s) => s.currentPage);
  const setPdfMeta = useProjectStore((s) => s.setPdfMeta);
  const setPageFabricState = useProjectStore((s) => s.setPageFabricState);
  const getPageFabricState = useProjectStore((s) => s.getPageFabricState);
  const tool = useProjectStore((s) => s.tool);
  const conditions = useProjectStore((s) => s.conditions);
  const pixelsPerFoot = useProjectStore((s) => s.pixelsPerFoot);
  const highlightNid = useProjectStore((s) => s.highlightNid);
  const setHighlightNid = useProjectStore((s) => s.setHighlightNid);
  const conditionRestyleRequest = useProjectStore(
    (s) => s.conditionRestyleRequest
  );

  useEffect(() => {
    const s = socketRef.current;
    if (!s) return;
    const onConnect = () => {
      mySidRef.current = s.id ?? null;
    };
    s.on('connect', onConnect);
    if (s.connected) onConnect();
    return () => {
      s.off('connect', onConnect);
    };
  }, [socketRef]);

  useEffect(() => {
    const socket = socketRef.current;
    if (!socket) return;
    const page0 = () => useProjectStore.getState().currentPage - 1;
    const docId = () =>
      useProjectStore.getState().activeDocumentId ?? 'default';

    const onAdd = (payload: {
      from?: string;
      page?: number;
      documentId?: string;
      json?: object;
    }) => {
      if (payload.from === mySidRef.current) return;
      const c = fabricRef.current;
      if (
        !c ||
        payload.page !== page0() ||
        (payload.documentId ?? 'default') !== docId() ||
        !payload.json
      )
        return;
      suppressRef.current.emit = true;
      suppressRef.current.undo = true;
      fabric.util.enlivenObjects(
        [payload.json],
        (objs: fabric.Object[]) => {
          objs.forEach((o) => {
            if (!(o as fabric.Object & { nid?: string }).nid)
              (o as fabric.Object & { nid?: string }).nid = nid();
            c.add(o);
          });
          c.renderAll();
          suppressRef.current.emit = false;
          suppressRef.current.undo = false;
        },
        ''
      );
    };

    const onMod = (payload: {
      from?: string;
      page?: number;
      documentId?: string;
      objectNid?: string;
      json?: object;
    }) => {
      if (payload.from === mySidRef.current) return;
      const c = fabricRef.current;
      if (
        !c ||
        payload.page !== page0() ||
        (payload.documentId ?? 'default') !== docId() ||
        !payload.json
      )
        return;
      const found = c
        .getObjects()
        .find(
          (o) => (o as fabric.Object & { nid?: string }).nid === payload.objectNid
        );
      if (!found) return;
      suppressRef.current.emit = true;
      suppressRef.current.undo = true;
      c.remove(found);
      fabric.util.enlivenObjects(
        [payload.json],
        (objs: fabric.Object[]) => {
          const n = objs[0];
          if (n) {
            (n as fabric.Object & { nid?: string }).nid = payload.objectNid;
            c.add(n);
          }
          c.renderAll();
          suppressRef.current.emit = false;
          suppressRef.current.undo = false;
        },
        ''
      );
    };

    const onRem = (payload: {
      from?: string;
      page?: number;
      documentId?: string;
      objectNid?: string;
    }) => {
      if (payload.from === mySidRef.current) return;
      const c = fabricRef.current;
      if (
        !c ||
        payload.page !== page0() ||
        (payload.documentId ?? 'default') !== docId()
      )
        return;
      const found = c
        .getObjects()
        .find(
          (o) => (o as fabric.Object & { nid?: string }).nid === payload.objectNid
        );
      if (found) {
        suppressRef.current.emit = true;
        suppressRef.current.undo = true;
        c.remove(found);
        suppressRef.current.emit = false;
        suppressRef.current.undo = false;
        c.renderAll();
      }
    };

    socket.on('object:add', onAdd);
    socket.on('object:modify', onMod);
    socket.on('object:remove', onRem);
    return () => {
      socket.off('object:add', onAdd);
      socket.off('object:modify', onMod);
      socket.off('object:remove', onRem);
    };
  }, [socketRef]);

  useEffect(() => {
    if (!pdfData) {
      pdfDocRef.current = null;
      setPdfMeta(0, null);
      return;
    }
    let cancelled = false;
    (async () => {
      const doc = await openPdfFromArrayBuffer(pdfData);
      if (cancelled) return;
      pdfDocRef.current = doc;
      setPdfMeta(doc.numPages, null);
      setPdfDocGeneration((n) => n + 1);
    })();
    return () => {
      cancelled = true;
    };
  }, [pdfData, setPdfMeta]);

  useEffect(() => {
    const el = fabricElRef.current;
    if (!el) return;
    const c = new fabric.Canvas(el, {
      selection: true,
      preserveObjectStacking: true,
      backgroundColor: 'transparent',
    });
    fabricRef.current = c;

    const syncPdfTransform = () => {
      const v = c.viewportTransform;
      const pc = pdfCanvasRef.current;
      if (!v || !pc) return;
      pc.style.transform = `translate(${v[4]}px,${v[5]}px) scale(${v[0]})`;
      pc.style.transformOrigin = '0 0';
    };

    let panning = false;
    let lx = 0;
    let ly = 0;

    const keys = FABRIC_KEYS as unknown as string[];

    const removeAiScopeRects = () => {
      c.getObjects().forEach((obj) => {
        if ((obj as fabric.Object & { aiScope?: boolean }).aiScope) {
          c.remove(obj);
        }
      });
    };

    const cancelAiScopeDrag = () => {
      const prev = aiScopePreviewRef.current;
      if (prev) {
        c.remove(prev);
        aiScopePreviewRef.current = null;
      }
      aiScopeDragRef.current = null;
    };

    const pushUndoLocal = () => {
      if (suppressRef.current.undo) return;
      const s = JSON.stringify(c.toJSON(keys));
      const u = undoRef.current;
      if (u.length && u[u.length - 1] === s) return;
      u.push(s);
      if (u.length > 80) u.shift();
      redoRef.current = [];
    };

    const finishPolyline = () => {
      const d = drawRef.current;
      if (!d || d.mode !== 'polyline' || d.points.length < 2) {
        drawRef.current = null;
        return;
      }
      const st = useProjectStore.getState();
      const pl = new fabric.Polyline(
        d.points.map((p) => ({ x: p.x, y: p.y })),
        { fill: '', objectCaching: false }
      );
      if (
        !applyStyleToObject(pl, st.conditions, st.selectedConditionIds)
      ) {
        drawRef.current = null;
        return;
      }
      (pl as fabric.Object & { markType?: string }).markType = 'polyline';
      c.add(pl);
      pushUndoLocal();
      drawRef.current = null;
      socketRef.current?.emit('object:add', {
        page: st.currentPage - 1,
        documentId: st.activeDocumentId ?? 'default',
        json: pl.toJSON(keys),
      });
    };

    c.on('mouse:down', (opt) => {
      const st = useProjectStore.getState();
      const t = st.tool;

      if (t === 'pan') {
        panning = true;
        lx = opt.e.clientX;
        ly = opt.e.clientY;
        c.defaultCursor = 'grabbing';
        return;
      }

      if (t === 'select') return;

      if (t === 'ai_scope') {
        const e = opt.e;
        if (e.button !== 0) return;
        const ptr = c.getPointer(e);
        cancelAiScopeDrag();
        removeAiScopeRects();
        aiScopeDragRef.current = { x: ptr.x, y: ptr.y };
        const preview = new fabric.Rect({
          left: ptr.x,
          top: ptr.y,
          width: 0,
          height: 0,
          fill: 'rgba(139, 92, 246, 0.14)',
          stroke: '#c4b5fd',
          strokeWidth: 2,
          strokeDashArray: [6, 4],
          selectable: false,
          evented: false,
        });
        (preview as fabric.Object & { isAiScopePreview?: boolean }).isAiScopePreview =
          true;
        aiScopePreviewRef.current = preview;
        c.add(preview);
        c.requestRenderAll();
        return;
      }

      const ids = st.selectedConditionIds.filter((id) =>
        st.conditions.some((c) => c.id === id)
      );
      if (!ids.length && t !== 'measure' && t !== 'text') return;

      const e = opt.e;
      if (e.button !== 0) return;
      const ptr = c.getPointer(e);

      if (t === 'line') {
        const d = drawRef.current;
        if (!d || d.mode !== 'line') {
          drawRef.current = { mode: 'line', a: ptr };
          return;
        }
        const ln = new fabric.Line([d.a.x, d.a.y, ptr.x, ptr.y], {});
        if (!applyStyleToObject(ln, st.conditions, st.selectedConditionIds))
          return;
        (ln as fabric.Object & { markType?: string }).markType = 'line';
        c.add(ln);
        pushUndoLocal();
        drawRef.current = null;
        socketRef.current?.emit('object:add', {
          page: st.currentPage - 1,
          documentId: st.activeDocumentId ?? 'default',
          json: ln.toJSON(keys),
        });
        return;
      }

      if (t === 'polyline') {
        const d = drawRef.current;
        if (!d || d.mode !== 'polyline') {
          drawRef.current = { mode: 'polyline', points: [ptr] };
          return;
        }
        d.points.push(ptr);
        return;
      }

      if (t === 'polygon') {
        const d = drawRef.current;
        if (!d || d.mode !== 'polygon') {
          drawRef.current = { mode: 'polygon', points: [ptr] };
          return;
        }
        d.points.push(ptr);
        return;
      }

      if (t === 'arc') {
        const d = drawRef.current;
        if (!d || d.mode !== 'arc') {
          drawRef.current = { mode: 'arc', pts: [ptr] };
          return;
        }
        if (d.pts.length === 1) {
          d.pts.push(ptr);
          return;
        }
        const [p0, p1] = d.pts;
        const pathStr = arcPathFromThreePoints(
          p0.x,
          p0.y,
          p1.x,
          p1.y,
          ptr.x,
          ptr.y
        );
        drawRef.current = null;
        if (!pathStr) return;
        const path = new fabric.Path(pathStr, {});
        if (!applyStyleToObject(path, st.conditions, st.selectedConditionIds))
          return;
        (path as fabric.Object & { markType?: string }).markType = 'arc';
        c.add(path);
        pushUndoLocal();
        socketRef.current?.emit('object:add', {
          page: st.currentPage - 1,
          documentId: st.activeDocumentId ?? 'default',
          json: path.toJSON(keys),
        });
        return;
      }

      if (t === 'count') {
        const circle = new fabric.Circle({
          left: ptr.x - 6,
          top: ptr.y - 6,
          radius: 6,
          originX: 'left',
          originY: 'top',
        });
        if (!applyStyleToObject(circle, st.conditions, st.selectedConditionIds))
          return;
        (circle as fabric.Object & { markType?: string }).markType = 'count';
        c.add(circle);
        pushUndoLocal();
        socketRef.current?.emit('object:add', {
          page: st.currentPage - 1,
          documentId: st.activeDocumentId ?? 'default',
          json: circle.toJSON(keys),
        });
        return;
      }

      if (t === 'measure') {
        const d = drawRef.current;
        if (!d || d.mode !== 'measure') {
          drawRef.current = { mode: 'measure', a: ptr };
          return;
        }
        const ln = new fabric.Line([d.a.x, d.a.y, ptr.x, ptr.y], {
          stroke: '#fbbf24',
          strokeDashArray: [4, 4],
          selectable: false,
          evented: false,
        });
        (ln as fabric.Object & { markType?: string }).markType = 'measure';
        c.add(ln);
        drawRef.current = null;
        return;
      }

      if (t === 'text') {
        const label = window.prompt('Note text');
        if (!label) return;
        const txt = new fabric.Text(label, {
          left: ptr.x,
          top: ptr.y,
          fontSize: 14,
          fill: '#e2e8f0',
          fontFamily: 'system-ui',
        });
        if (!applyStyleToObject(txt, st.conditions, st.selectedConditionIds))
          return;
        (txt as fabric.Object & { markType?: string }).markType = 'text';
        (txt as fabric.Object & { notes?: string }).notes = label;
        c.add(txt);
        pushUndoLocal();
        socketRef.current?.emit('object:add', {
          page: st.currentPage - 1,
          documentId: st.activeDocumentId ?? 'default',
          json: txt.toJSON(keys),
        });
      }
    });

    c.on('mouse:up', () => {
      panning = false;
      const stUp = useProjectStore.getState();
      if (stUp.tool === 'pan') c.defaultCursor = 'grab';

      const drag = aiScopeDragRef.current;
      const previewUp = aiScopePreviewRef.current;
      if (drag && previewUp) {
        const prev = previewUp;
        const w = prev.width ?? 0;
        const h = prev.height ?? 0;
        const left = prev.left ?? 0;
        const top = prev.top ?? 0;
        c.remove(prev);
        aiScopePreviewRef.current = null;
        aiScopeDragRef.current = null;
        if (w > 8 && h > 8) {
          const final = new fabric.Rect({
            left,
            top,
            width: w,
            height: h,
            fill: 'rgba(139, 92, 246, 0.11)',
            stroke: '#a78bfa',
            strokeWidth: 2,
            strokeDashArray: [8, 5],
            selectable: true,
            evented: true,
          });
          const fm = final as fabric.Object & {
            aiScope?: boolean;
            nid?: string;
          };
          fm.aiScope = true;
          fm.nid = nid();
          c.add(final);
          pushUndoLocal();
          socketRef.current?.emit('object:add', {
            page: stUp.currentPage - 1,
            documentId: stUp.activeDocumentId ?? 'default',
            json: final.toJSON(keys),
          });
        }
        c.requestRenderAll();
      }
    });

    c.on('mouse:move', (opt) => {
      const stMv = useProjectStore.getState();
      const dragM = aiScopeDragRef.current;
      const previewM = aiScopePreviewRef.current;
      if (stMv.tool === 'ai_scope' && dragM && previewM) {
        const ptr = c.getPointer(opt.e);
        const x0 = dragM.x;
        const y0 = dragM.y;
        previewM.set({
          left: Math.min(x0, ptr.x),
          top: Math.min(y0, ptr.y),
          width: Math.abs(ptr.x - x0),
          height: Math.abs(ptr.y - y0),
        });
        previewM.setCoords();
        c.requestRenderAll();
        return;
      }
      if (!panning || stMv.tool !== 'pan') return;
      const e = opt.e;
      const dx = e.clientX - lx;
      const dy = e.clientY - ly;
      lx = e.clientX;
      ly = e.clientY;
      const v = c.viewportTransform!;
      v[4] += dx;
      v[5] += dy;
      c.requestRenderAll();
      syncPdfTransform();
    });

    c.on('mouse:wheel', (opt) => {
      const delta = opt.e.deltaY;
      let z = c.getZoom() * 0.999 ** delta;
      z = Math.min(6, Math.max(0.12, z));
      c.zoomToPoint({ x: opt.e.offsetX, y: opt.e.offsetY } as fabric.Point, z);
      opt.e.preventDefault();
      syncPdfTransform();
    });

    c.on('object:modified', (e) => {
      pushUndoLocal();
      const st = useProjectStore.getState();
      const o = e.target as fabric.Object & { nid?: string };
      socketRef.current?.emit('object:modify', {
        page: st.currentPage - 1,
        documentId: st.activeDocumentId ?? 'default',
        objectNid: o.nid,
        json: o.toJSON(keys),
      });
    });

    c.on('object:removed', (e) => {
      if (suppressRef.current.undo) return;
      const o = e.target as fabric.Object & { nid?: string };
      pushUndoLocal();
      if (o.nid) {
        socketRef.current?.emit('object:remove', {
          page: useProjectStore.getState().currentPage - 1,
          documentId:
            useProjectStore.getState().activeDocumentId ?? 'default',
          objectNid: o.nid,
        });
      }
    });

    c.on('mouse:dblclick', () => {
      if (useProjectStore.getState().tool === 'polyline') finishPolyline();
    });

    const onKey = (ev: KeyboardEvent) => {
      if (
        (ev.key === 'Delete' || ev.key === 'Backspace') &&
        !ev.ctrlKey &&
        ['INPUT', 'TEXTAREA', 'SELECT'].indexOf(
          (document.activeElement?.tagName || '').toUpperCase()
        ) < 0
      ) {
        const st = useProjectStore.getState();
        if (st.tool === 'select') {
          const active = c.getActiveObjects();
          if (active.length) {
            ev.preventDefault();
            active.forEach((o) => c.remove(o));
            c.discardActiveObject();
            c.requestRenderAll();
          }
        }
      }
      if (ev.key === 'Enter') {
        const st = useProjectStore.getState();
        if (st.tool === 'polygon') {
          const d = drawRef.current;
          if (d?.mode === 'polygon' && d.points.length >= 3) {
            const pg = new fabric.Polygon(
              d.points.map((p) => ({ x: p.x, y: p.y })),
              { objectCaching: false }
            );
            if (
              applyStyleToObject(pg, st.conditions, st.selectedConditionIds)
            ) {
              (pg as fabric.Object & { markType?: string }).markType = 'polygon';
              c.add(pg);
              pushUndoLocal();
              socketRef.current?.emit('object:add', {
                page: st.currentPage - 1,
                documentId: st.activeDocumentId ?? 'default',
                json: pg.toJSON(keys),
              });
            }
            drawRef.current = null;
          }
        }
        if (st.tool === 'polyline') finishPolyline();
      }
      if (ev.key === ' ' && ev.target === document.body) {
        ev.preventDefault();
        useProjectStore.getState().setTool('pan');
      }
    };
    window.addEventListener('keydown', onKey);

    (window as unknown as { __takeoffPushUndoSnapshot?: () => void }).__takeoffPushUndoSnapshot =
      pushUndoLocal;
    (window as unknown as { __takeoffClearAiFocus?: () => void }).__takeoffClearAiFocus =
      () => {
        cancelAiScopeDrag();
        removeAiScopeRects();
        c.requestRenderAll();
        pushUndoLocal();
      };
    (window as unknown as { __takeoffCanvas?: fabric.Canvas }).__takeoffCanvas =
      c;
    (window as unknown as { __takeoffUndo?: () => void }).__takeoffUndo =
      () => {
        const u = undoRef.current;
        if (u.length < 2) return;
        const cur = u.pop()!;
        redoRef.current.push(cur);
        const prev = u[u.length - 1];
        suppressRef.current.undo = true;
        suppressRef.current.emit = true;
        c.loadFromJSON(prev, () => {
          c.renderAll();
          suppressRef.current.undo = false;
          suppressRef.current.emit = false;
        });
      };
    const polygonAbs = (o: fabric.Polygon) => {
      const po = o.pathOffset || { x: 0, y: 0 };
      return (o.points || []).map((p) => ({
        x: p.x - po.x + (o.left || 0),
        y: p.y - po.y + (o.top || 0),
      }));
    };

    const syncSelection = () => {
      const a = c.getActiveObject();
      if (!a) {
        useProjectStore.getState().setSelectedMark(null, null);
        return;
      }
      const ext = a as fabric.Object & {
        nid?: string;
        conditionIds?: string[];
        markType?: string;
        notes?: string;
        aiScope?: boolean;
      };
      if (ext.aiScope) {
        useProjectStore.getState().setSelectedMark(null, null);
        return;
      }
      const px = useProjectStore.getState().pixelsPerFoot;
      let lengthFt: number | undefined;
      let areaSf: number | undefined;
      if (a.type === 'line') {
        lengthFt = feetFromPixels(
          fabricLineLength(a as fabric.Line),
          px
        );
      }
      if (a.type === 'polygon') {
        const pts = polygonAbs(a as fabric.Polygon);
        areaSf = sqFeetFromPixels(polygonAreaPx(pts), px);
      }
      useProjectStore.getState().setSelectedMark(ext.nid ?? null, {
        markType: ext.markType,
        conditionIds: ext.conditionIds,
        notes: ext.notes,
        lengthFt,
        areaSf,
      });
    };

    c.on('selection:created', syncSelection);
    c.on('selection:updated', syncSelection);
    c.on('selection:cleared', () =>
      useProjectStore.getState().setSelectedMark(null, null)
    );

    (window as unknown as { __takeoffRedo?: () => void }).__takeoffRedo =
      () => {
        const r = redoRef.current;
        if (!r.length) return;
        const next = r.pop()!;
        undoRef.current.push(next);
        suppressRef.current.undo = true;
        suppressRef.current.emit = true;
        c.loadFromJSON(next, () => {
          c.renderAll();
          suppressRef.current.undo = false;
          suppressRef.current.emit = false;
        });
      };

    return () => {
      window.removeEventListener('keydown', onKey);
      delete (window as unknown as { __takeoffCanvas?: fabric.Canvas })
        .__takeoffCanvas;
      delete (window as unknown as { __takeoffPushUndoSnapshot?: () => void })
        .__takeoffPushUndoSnapshot;
      delete (window as unknown as { __takeoffClearAiFocus?: () => void })
        .__takeoffClearAiFocus;
      delete (window as unknown as { __takeoffUndo?: () => void }).__takeoffUndo;
      delete (window as unknown as { __takeoffRedo?: () => void }).__takeoffRedo;
      c.dispose();
      fabricRef.current = null;
    };
  }, [socketRef]);

  useEffect(() => {
    const c = fabricRef.current;
    if (!c) return;
    const t = tool;
    if (t === 'ai_scope') {
      c.selection = false;
      c.defaultCursor = 'crosshair';
      c.forEachObject((o) => {
        o.selectable = false;
        o.evented = false;
      });
      c.renderAll();
      return;
    }
    c.getObjects().slice().forEach((o) => {
      if (
        (o as fabric.Object & { isAiScopePreview?: boolean }).isAiScopePreview
      ) {
        c.remove(o);
      }
    });
    aiScopeDragRef.current = null;
    aiScopePreviewRef.current = null;

    c.selection = t === 'select';
    c.defaultCursor =
      t === 'pan' ? 'grab' : t === 'select' ? 'default' : 'crosshair';
    c.forEachObject((o) => {
      o.selectable = t === 'select';
      o.evented = t === 'select' || t === 'pan';
    });
    if (t === 'pan') {
      c.forEachObject((o) => {
        o.selectable = false;
        o.evented = false;
      });
    }
    c.renderAll();
  }, [tool]);

  useEffect(() => {
    const c = fabricRef.current;
    if (!c || !highlightNid) return;
    const o = c
      .getObjects()
      .find((x) => (x as fabric.Object & { nid?: string }).nid === highlightNid);
    if (o) {
      c.setActiveObject(o);
      c.renderAll();
    }
    setHighlightNid(null);
  }, [highlightNid, setHighlightNid]);

  useEffect(() => {
    const doc = pdfDocRef.current;
    const pdfCv = pdfCanvasRef.current;
    const c = fabricRef.current;
    if (!doc || !pdfCv || !c || !pdfData) return;

    const pageIndex0 = currentPage - 1;
    const keys = FABRIC_KEYS as unknown as string[];

    let cancelled = false;
    (async () => {
      const page = await doc.getPage(currentPage);
      if (cancelled) return;
      const viewport = page.getViewport({ scale: 1.2 });
      const ctx = pdfCv.getContext('2d');
      if (!ctx) return;
      pdfCv.width = viewport.width;
      pdfCv.height = viewport.height;
      pdfCv.style.width = `${viewport.width}px`;
      pdfCv.style.height = `${viewport.height}px`;
      await page.render({ canvasContext: ctx, viewport }).promise;
      if (cancelled) return;
      c.setDimensions({ width: viewport.width, height: viewport.height });
      c.calcOffset();

      const saved = getPageFabricState(pageIndex0);
      suppressRef.current.undo = true;
      suppressRef.current.emit = true;
      if (saved) {
        await new Promise<void>((res) => {
          c.loadFromJSON(saved, () => {
            c.renderAll();
            res();
          });
        });
      } else {
        c.clear();
        c.backgroundColor = 'transparent';
        c.renderAll();
      }
      suppressRef.current.undo = false;
      suppressRef.current.emit = false;
      undoRef.current = [JSON.stringify(c.toJSON(keys))];
      redoRef.current = [];
    })();

    return () => {
      cancelled = true;
      const c2 = fabricRef.current;
      if (c2) {
        c2.getObjects().slice().forEach((o) => {
          if (
            (o as fabric.Object & { isAiScopePreview?: boolean })
              .isAiScopePreview
          ) {
            c2.remove(o);
          }
        });
        setPageFabricState(pageIndex0, c2.toJSON(keys));
      }
    };
  }, [
    pdfData,
    pdfDocGeneration,
    currentPage,
    getPageFabricState,
    setPageFabricState,
  ]);

  useEffect(() => {
    (window as unknown as { __takeoffExport?: () => ReturnType<typeof rowsFromCanvasPage> }).__takeoffExport =
      () => {
        const c = fabricRef.current;
        if (!c) return [];
        return rowsFromCanvasPage(
          c,
          currentPage,
          conditions,
          pixelsPerFoot
        );
      };
  }, [currentPage, conditions, pixelsPerFoot]);

  useEffect(() => {
    const req = conditionRestyleRequest;
    if (!req || !fabricRef.current) return;
    const c = fabricRef.current;
    const conds = useProjectStore.getState().conditions;
    let selectedNids: Set<string> | null = null;
    if (req.scope === 'selection') {
      selectedNids = new Set(
        c
          .getActiveObjects()
          .map((o) => (o as fabric.Object & { nid?: string }).nid)
          .filter((n): n is string => typeof n === 'string' && n.length > 0)
      );
      if (selectedNids.size === 0) {
        useProjectStore.setState({ conditionRestyleRequest: null });
        return;
      }
    }
    for (const o of c.getObjects()) {
      const ext = o as fabric.Object & {
        conditionIds?: string[];
        nid?: string;
        isBoost?: boolean;
      };
      if (ext.isBoost || (ext as fabric.Object & { aiScope?: boolean }).aiScope)
        continue;
      const cids = ext.conditionIds;
      if (!cids?.some((i) => req.conditionIds.includes(i))) continue;
      if (selectedNids && (!ext.nid || !selectedNids.has(ext.nid))) continue;
      applyConditionVisualToFabricObject(o, cids, conds);
      o.setCoords();
    }
    c.requestRenderAll();
    const snap = (
      window as unknown as { __takeoffPushUndoSnapshot?: () => void }
    ).__takeoffPushUndoSnapshot;
    snap?.();
    useProjectStore.setState({ conditionRestyleRequest: null });
  }, [conditionRestyleRequest]);

  return (
    <div
      ref={wrapRef}
      className="canvas-stack min-h-[520px] rounded-xl border border-ost-border/80 shadow-[0_8px_28px_rgba(0,0,0,0.45)]"
    >
      <canvas ref={pdfCanvasRef} className="pdf-canvas" />
      <canvas ref={fabricElRef} className="upper-canvas" />
    </div>
  );
}
