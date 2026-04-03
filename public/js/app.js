import * as pdfjsLib from 'https://unpkg.com/pdfjs-dist@4.4.168/build/pdf.mjs';

pdfjsLib.GlobalWorkerOptions.workerSrc =
  'https://unpkg.com/pdfjs-dist@4.4.168/build/pdf.worker.mjs';

const CUSTOM_PROPS = [
  'takeoffLayerId',
  'objectNid',
  'isBot',
  'assemblyId',
  'takeoffKind',
];

function nid() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
}

function pxPerFt() {
  const el = document.getElementById('scale-px-per-ft');
  const v = parseFloat(el?.value);
  return Number.isFinite(v) && v > 0 ? v : 48;
}

function ftFromPx(lenPx) {
  return lenPx / pxPerFt();
}

function sqFtFromPxArea(areaPx) {
  const s = pxPerFt();
  return areaPx / (s * s);
}

/** @type {fabric.Canvas} */
let canvas;
let pdfDoc = null;
let pdfPageNum = 1;
let pdfScale = 1;
let activeLayerId = null;
let tool = 'select';
let socket = null;
let mySocketId = null;
let suppressEmit = false;
let suppressUndo = false;

const defaultLayers = () => [];

let layers = loadJson('takeoff-layers', defaultLayers());
let rates = loadJson('takeoff-rates', {});
let assemblies = loadJson('takeoff-assemblies', []);

/** pageIndex -> fabric JSON */
const pageSnapshots = new Map();

const undoStack = [];
const redoStack = [];
const UNDO_MAX = 80;

function loadJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (raw) return JSON.parse(raw);
  } catch (_) {}
  return fallback;
}

function saveLayers() {
  localStorage.setItem('takeoff-layers', JSON.stringify(layers));
}

function saveAssemblies() {
  localStorage.setItem('takeoff-assemblies', JSON.stringify(assemblies));
}

function saveRates() {
  localStorage.setItem('takeoff-rates', JSON.stringify(rates));
}

function layerById(id) {
  if (id == null || id === '') {
    return (
      layers.find((l) => l.id === activeLayerId) ||
      layers[0] || {
        id: '',
        name: 'Unassigned',
        color: '#888',
        kind: 'linear',
      }
    );
  }
  const found = layers.find((l) => l.id === id);
  if (found) return found;
  return {
    id,
    name: String(id),
    color: '#888',
    kind: 'linear',
  };
}

function renderLayerList() {
  const ul = document.getElementById('layer-list');
  ul.innerHTML = '';
  if (!layers.length) {
    const empty = document.createElement('li');
    empty.className = 'layer-empty';
    empty.textContent = 'No types yet — use + Type to add one.';
    ul.appendChild(empty);
  }
  layers.forEach((L) => {
    const li = document.createElement('li');
    if (L.id === activeLayerId) li.classList.add('active');
    li.innerHTML = `
      <span class="layer-swatch" style="background:${L.color}"></span>
      <div class="layer-meta">
        <div>${escapeHtml(L.name)}</div>
        <div class="layer-kind">${L.kind}</div>
      </div>
    `;
    li.addEventListener('click', () => {
      activeLayerId = L.id;
      renderLayerList();
      setStatus(`Active: ${L.name}`);
    });
    ul.appendChild(li);
  });

  const sel = document.getElementById('assembly-apply');
  if (sel) {
    sel.innerHTML = assemblies
      .map(
        (a) =>
          `<option value="${escapeHtml(a.id)}">${escapeHtml(a.name)}</option>`
      )
      .join('');
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/"/g, '&quot;');
}

function polygonAreaPx(points) {
  let a = 0;
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    a += points[i].x * points[j].y - points[j].x * points[i].y;
  }
  return Math.abs(a / 2);
}

function lineLengthPx(x1, y1, x2, y2) {
  return Math.hypot(x2 - x1, y2 - y1);
}

function fabricLineLengthPx(o) {
  if (o.type !== 'line' || !o.calcLinePoints) {
    return lineLengthPx(o.x1, o.y1, o.x2, o.y2);
  }
  const p = o.calcLinePoints();
  return Math.hypot(p.x2 - p.x1, p.y2 - p.y1);
}

function pathLengthApprox(pathObj) {
  const p = pathObj.path;
  if (!p || !p.length) return 0;
  let len = 0;
  let cx = 0;
  let cy = 0;
  let sx = 0;
  let sy = 0;
  for (const seg of p) {
    const cmd = seg[0];
    if (cmd === 'M') {
      cx = seg[1];
      cy = seg[2];
      sx = cx;
      sy = cy;
    } else if (cmd === 'L') {
      len += Math.hypot(seg[1] - cx, seg[2] - cy);
      cx = seg[1];
      cy = seg[2];
    } else if (cmd === 'A') {
      const rx = seg[1];
      const ry = seg[2];
      const x = seg[6];
      const y = seg[7];
      const r = (rx + ry) / 2;
      const chord = Math.hypot(x - cx, y - cy);
      const theta = 2 * Math.asin(Math.min(1, chord / (2 * r)));
      len += r * theta;
      cx = x;
      cy = y;
    } else if (cmd === 'Z' || cmd === 'z') {
      len += Math.hypot(sx - cx, sy - cy);
      cx = sx;
      cy = sy;
    }
  }
  return len;
}

function polygonAbsolutePoints(o) {
  const po = o.pathOffset || { x: 0, y: 0 };
  return (o.points || []).map((p) => ({
    x: p.x - po.x + (o.left || 0),
    y: p.y - po.y + (o.top || 0),
  }));
}

function computeTotals() {
  const acc = {};
  layers.forEach((L) => {
    acc[L.id] = { linearFt: 0, sqFt: 0, count: 0, layer: L };
  });

  canvas.getObjects().forEach((o) => {
    if (o.excludeFromExport) return;
    const lid = o.takeoffLayerId || activeLayerId;
    if (lid == null || lid === '' || !acc[lid]) return;
    const L = layerById(lid);

    const kind = o.takeoffKind || L.kind;

    if (o.isBot) return;

    if (kind === 'count' || o.takeoffKind === 'count') {
      acc[lid].count += 1;
      return;
    }

    if (o.type === 'line') {
      const len = fabricLineLengthPx(o);
      if (kind === 'linear') acc[lid].linearFt += ftFromPx(len);
      return;
    }

    if (o.type === 'polyline') {
      const pts = o.points || [];
      let len = 0;
      const ax = o.left || 0;
      const ay = o.top || 0;
      for (let i = 1; i < pts.length; i++) {
        len += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
      }
      if (kind === 'linear') acc[lid].linearFt += ftFromPx(len);
      return;
    }

    if (o.type === 'polygon') {
      const pts = polygonAbsolutePoints(o);
      if (kind === 'area' && pts.length >= 3) {
        acc[lid].sqFt += sqFtFromPxArea(polygonAreaPx(pts));
      } else if (kind === 'linear' && pts.length >= 2) {
        let len = 0;
        for (let i = 0; i < pts.length; i++) {
          const j = (i + 1) % pts.length;
          len += Math.hypot(pts[j].x - pts[i].x, pts[j].y - pts[i].y);
        }
        acc[lid].linearFt += ftFromPx(len);
      }
      return;
    }

    if (o.type === 'path') {
      const plen = pathLengthApprox(o);
      if (kind === 'linear') acc[lid].linearFt += ftFromPx(plen);
      return;
    }

    if (o.type === 'circle' && o.radius) {
      acc[lid].count += 1;
    }
  });

  /* Assembly extensions: wall face sq ft from linear * assembly height */
  canvas.getObjects().forEach((o) => {
    if (o.isBot || !o.assemblyId) return;
    const asm = assemblies.find((a) => a.id === o.assemblyId);
    if (!asm || !asm.heightFt) return;
    const L = layerById(o.takeoffLayerId);
    const kind = o.takeoffKind || L.kind;
    let lenPx = 0;
    if (o.type === 'line') lenPx = fabricLineLengthPx(o);
    else if (o.type === 'polyline' && o.points) {
      for (let i = 1; i < o.points.length; i++) {
        lenPx += Math.hypot(
          o.points[i].x - o.points[i - 1].x,
          o.points[i].y - o.points[i - 1].y
        );
      }
    }
    if (kind === 'linear' && lenPx > 0) {
      const lid = o.takeoffLayerId;
      if (!lid || !acc[lid]) return;
      if (!acc[`${lid}::_asm_surface`]) {
        acc[`${lid}::_asm_surface`] = {
          linearFt: 0,
          sqFt: 0,
          count: 0,
          layer: { name: `${L.name} (assembly face)`, kind: 'area' },
        };
      }
      acc[`${lid}::_asm_surface`].sqFt += ftFromPx(lenPx) * asm.heightFt;
    }
  });

  return acc;
}

function renderTotals() {
  const acc = computeTotals();
  const el = document.getElementById('totals');
  const parts = [];
  Object.keys(acc).forEach((key) => {
    const { linearFt, sqFt, count, layer } = acc[key];
    const rate = rates[key] ?? rates[layer.id] ?? '';
    const has =
      linearFt > 0.001 || sqFt > 0.001 || count > 0 || key.includes('_asm');
    if (!has) return;
    const bits = [];
    if (linearFt > 0.001) bits.push(`${linearFt.toFixed(1)} lf`);
    if (sqFt > 0.001) bits.push(`${sqFt.toFixed(1)} sf`);
    if (count > 0) bits.push(`${count} ct`);
    const sub = bits.join(' · ');
    const r = parseFloat(rate);
    let cost = '';
    if (Number.isFinite(r) && r !== 0) {
      let base = 0;
      if (linearFt > 0.001) base += linearFt * r;
      else if (sqFt > 0.001) base += sqFt * r;
      else if (count > 0) base += count * r;
      cost = ` → $${base.toFixed(2)}`;
    }
    parts.push(`
      <div class="total-row">
        <span>${escapeHtml(layer.name)}</span>
        <span class="qty">${escapeHtml(sub)}${escapeHtml(cost)}</span>
      </div>
      <div class="rate-inline">
        <label>$ / unit <input type="number" data-rate-key="${escapeHtml(key)}" step="0.01" value="${escapeHtml(String(rate))}" placeholder="0" /></label>
      </div>
    `);
  });
  el.innerHTML =
    parts.join('') ||
    (layers.length
      ? '<p class="hint">Draw on the plan to see totals.</p>'
      : '<p class="hint">Add a takeoff type, then select it before drawing.</p>');

  el.querySelectorAll('input[data-rate-key]').forEach((inp) => {
    inp.addEventListener('change', () => {
      rates[inp.dataset.rateKey] = inp.value;
      saveRates();
      renderTotals();
    });
  });
}

function snapshotCanvas() {
  return canvas.toJSON(CUSTOM_PROPS);
}

function pushUndoState() {
  if (suppressUndo) return;
  const s = JSON.stringify(snapshotCanvas());
  if (undoStack.length && undoStack[undoStack.length - 1] === s) return;
  undoStack.push(s);
  if (undoStack.length > UNDO_MAX) undoStack.shift();
  redoStack.length = 0;
}

function restoreSnapshot(jsonStr) {
  suppressEmit = true;
  suppressUndo = true;
  canvas.loadFromJSON(jsonStr, () => {
    canvas.renderAll();
    suppressEmit = false;
    suppressUndo = false;
    renderTotals();
  });
}

function undo() {
  if (undoStack.length < 2) return;
  const cur = undoStack.pop();
  redoStack.push(cur);
  const prev = undoStack[undoStack.length - 1];
  restoreSnapshot(prev);
}

function redo() {
  if (!redoStack.length) return;
  const next = redoStack.pop();
  undoStack.push(next);
  restoreSnapshot(next);
}

function savePageState() {
  if (!canvas) return;
  pageSnapshots.set(pdfPageNum - 1, snapshotCanvas());
}

function loadPageState() {
  const raw = pageSnapshots.get(pdfPageNum - 1);
  suppressEmit = true;
  suppressUndo = true;
  if (raw) {
    canvas.loadFromJSON(raw, () => {
      canvas.renderAll();
      suppressEmit = false;
      suppressUndo = false;
      undoStack.length = 0;
      redoStack.length = 0;
      pushUndoState();
      renderTotals();
    });
  } else {
    canvas.clear();
    canvas.backgroundColor = 'transparent';
    canvas.renderAll();
    suppressEmit = false;
    suppressUndo = false;
    undoStack.length = 0;
    redoStack.length = 0;
    pushUndoState();
    renderTotals();
  }
}

function setStatus(t) {
  const s = document.getElementById('status');
  if (s) s.textContent = t;
}

function updateZoomLabel() {
  const z = Math.round((canvas.getZoom() || 1) * 100);
  const el = document.getElementById('zoom-label');
  if (el) el.textContent = `${z}%`;
}

let drawState = null;

function applyToolStyle(obj) {
  const L = layers.find((l) => l.id === activeLayerId);
  if (!L) return false;
  obj.set({
    stroke: L.color,
    strokeWidth: 2,
    fill:
      L.kind === 'area'
        ? hexToRgba(L.color, 0.15)
        : 'transparent',
    takeoffLayerId: L.id,
    takeoffKind: L.kind,
    objectNid: nid(),
    isBot: false,
  });
  if (obj.type === 'circle') {
    obj.set({ fill: hexToRgba(L.color, 0.35), strokeWidth: 2 });
  }
  return true;
}

function hexToRgba(hex, a) {
  const h = hex.replace('#', '');
  const n = parseInt(h, 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r},${g},${b},${a})`;
}

function attachDrawingHandlers() {
  canvas.on('mouse:down', onMouseDown);
  canvas.on('mouse:move', onMouseMove);
  canvas.on('mouse:dblclick', onDblClick);
}

function onDblClick(opt) {
  if (tool === 'polyline' && drawState?.mode === 'polyline') {
    finishPolyline();
  }
}

function finishPolyline() {
  if (!drawState || drawState.mode !== 'polyline') return;
  const pts = drawState.points;
  if (pts.length < 2) {
    drawState = null;
    return;
  }
  const pl = new fabric.Polyline(
    pts.map((p) => ({ x: p.x, y: p.y })),
    { stroke: '#000', fill: '', objectCaching: false }
  );
  if (!applyToolStyle(pl)) {
    setStatus('Add a takeoff type first');
    drawState = null;
    return;
  }
  canvas.add(pl);
  canvas.setActiveObject(pl);
  pushUndoState();
  drawState = null;
  emitAdd(pl);
  renderTotals();
  setStatus('Polyline added');
}

function finishPolygon() {
  if (!drawState || drawState.mode !== 'polygon') return;
  const pts = drawState.points;
  if (pts.length < 3) {
    drawState = null;
    return;
  }
  const pg = new fabric.Polygon(
    pts.map((p) => ({ x: p.x, y: p.y })),
    { objectCaching: false }
  );
  if (!applyToolStyle(pg)) {
    setStatus('Add a takeoff type first');
    drawState = null;
    return;
  }
  canvas.add(pg);
  canvas.setActiveObject(pg);
  pushUndoState();
  drawState = null;
  emitAdd(pg);
  renderTotals();
  setStatus('Polygon added');
}

function onMouseDown(opt) {
  if (tool === 'select' || tool === 'pan') return;
  const e = opt.e;
  if (tool === 'pan') return;
  const ptr = canvas.getPointer(e);

  if (
    tool !== 'select' &&
    tool !== 'pan' &&
    (!layers.length || !layers.some((l) => l.id === activeLayerId))
  ) {
    setStatus('Add and select a takeoff type first');
    return;
  }

  if (tool === 'count') {
    const c = new fabric.Circle({
      left: ptr.x - 6,
      top: ptr.y - 6,
      radius: 6,
      originX: 'left',
      originY: 'top',
    });
    if (!applyToolStyle(c)) {
      setStatus('Add a takeoff type first');
      return;
    }
    c.set({ takeoffKind: 'count' });
    canvas.add(c);
    pushUndoState();
    emitAdd(c);
    renderTotals();
    return;
  }

  if (tool === 'line') {
    if (!drawState || drawState.mode !== 'line') {
      drawState = { mode: 'line', a: ptr };
      setStatus('Line: click end point');
      return;
    }
    const ln = new fabric.Line(
      [drawState.a.x, drawState.a.y, ptr.x, ptr.y],
      {}
    );
    if (!applyToolStyle(ln)) {
      setStatus('Add a takeoff type first');
      drawState = null;
      return;
    }
    canvas.add(ln);
    canvas.setActiveObject(ln);
    pushUndoState();
    drawState = null;
    emitAdd(ln);
    renderTotals();
    setStatus('Line added');
    return;
  }

  if (tool === 'polyline') {
    if (!drawState || drawState.mode !== 'polyline') {
      drawState = { mode: 'polyline', points: [ptr] };
      setStatus('Polyline: click points, double-click or Enter to finish');
      return;
    }
    drawState.points.push(ptr);
    return;
  }

  if (tool === 'polygon') {
    if (!drawState || drawState.mode !== 'polygon') {
      drawState = { mode: 'polygon', points: [ptr] };
      setStatus('Polygon: click vertices, press Enter to close');
      return;
    }
    drawState.points.push(ptr);
    return;
  }

  if (tool === 'arc') {
    if (!drawState || drawState.mode !== 'arc') {
      drawState = { mode: 'arc', pts: [ptr] };
      setStatus('Arc: click second point');
      return;
    }
    if (drawState.pts.length === 1) {
      drawState.pts.push(ptr);
      setStatus('Arc: click point on arc');
      return;
    }
    const [p0, p1] = drawState.pts;
    const p2 = ptr;
    const pathStr = arcPathFromThreePoints(p0.x, p0.y, p1.x, p1.y, p2.x, p2.y);
    if (!pathStr) {
      drawState = null;
      setStatus('Arc: points too straight, try again');
      return;
    }
    const path = new fabric.Path(pathStr, { objectCaching: false });
    if (!applyToolStyle(path)) {
      setStatus('Add a takeoff type first');
      drawState = null;
      return;
    }
    canvas.add(path);
    canvas.setActiveObject(path);
    pushUndoState();
    drawState = null;
    emitAdd(path);
    renderTotals();
    setStatus('Arc added');
  }
}

function onMouseMove(opt) {
  if (!drawState) return;
  canvas.renderAll();
}

function arcPathFromThreePoints(x1, y1, x2, y2, x3, y3) {
  const ax = x1 - x2;
  const ay = y1 - y2;
  const bx = x1 - x3;
  const by = y1 - y3;
  const cx = x2 - x3;
  const cy = y2 - y3;
  const d = 2 * (ax * (y2 - y3) + bx * (y3 - y1) + cx * (y1 - y2));
  if (Math.abs(d) < 1e-4) return null;
  const aSq = x1 * x1 + y1 * y1;
  const bSq = x2 * x2 + y2 * y2;
  const cSq = x3 * x3 + y3 * y3;
  const ux =
    (aSq * (y2 - y3) + bSq * (y3 - y1) + cSq * (y1 - y2)) / d;
  const uy =
    (aSq * (x3 - x2) + bSq * (x1 - x3) + cSq * (x2 - x1)) / d;
  const r = Math.hypot(x1 - ux, y1 - uy);
  if (r < 1) return null;

  const ang = (x, y) => Math.atan2(y - uy, x - ux);
  let a0 = ang(x1, y1);
  let a1 = ang(x3, y3);
  const am = ang(x2, y2);
  const norm = (t) => {
    while (t < 0) t += Math.PI * 2;
    while (t >= Math.PI * 2) t -= Math.PI * 2;
    return t;
  };
  const between = (t, lo, hi) => {
    t = norm(t);
    lo = norm(lo);
    hi = norm(hi);
    if (lo < hi) return t >= lo && t <= hi;
    return t >= lo || t <= hi;
  };
  let sweep = between(am, a0, a1) ? 0 : 1;
  const large = Math.abs(a1 - a0) > Math.PI ? 1 : 0;

  const polar = (cx, cy, r, a) => ({
    x: cx + r * Math.cos(a),
    y: cy + r * Math.sin(a),
  });
  const pStart = polar(ux, uy, r, a0);
  const pEnd = polar(ux, uy, r, a1);
  return [
    'M',
    pStart.x,
    pStart.y,
    'A',
    r,
    r,
    0,
    large,
    sweep,
    pEnd.x,
    pEnd.y,
  ].join(' ');
}

function emitAdd(obj) {
  if (suppressEmit || !socket) return;
  socket.emit('object:add', {
    page: pdfPageNum - 1,
    json: obj.toJSON(CUSTOM_PROPS),
  });
}

function emitModify(obj) {
  if (suppressEmit || !socket) return;
  socket.emit('object:modify', {
    page: pdfPageNum - 1,
    objectNid: obj.objectNid,
    json: obj.toJSON(CUSTOM_PROPS),
  });
}

function emitRemove(obj) {
  if (suppressEmit || !socket) return;
  socket.emit('object:remove', {
    page: pdfPageNum - 1,
    objectNid: obj.objectNid,
  });
}

function wireCollab() {
  if (typeof io !== 'function') return;
  socket = io();
  socket.on('connect', () => {
    mySocketId = socket.id;
    setStatus(`Connected ${socket.id.slice(0, 6)}…`);
  });

  socket.on('object:add', (payload) => {
    if (payload.from === mySocketId) return;
    if (payload.page !== pdfPageNum - 1) {
      let cur = pageSnapshots.get(payload.page);
      if (!cur || !cur.objects) {
        cur = { version: fabric.version, objects: [] };
      }
      cur.objects.push(payload.json);
      pageSnapshots.set(payload.page, cur);
      return;
    }
    suppressEmit = true;
    suppressUndo = true;
    fabric.util.enlivenObjects([payload.json], (objs) => {
      objs.forEach((o) => {
        if (!o.objectNid) o.set({ objectNid: nid() });
        canvas.add(o);
      });
      suppressEmit = false;
      suppressUndo = false;
      canvas.renderAll();
      renderTotals();
    });
  });

  socket.on('object:modify', (payload) => {
    if (payload.from === mySocketId) return;
    if (payload.page !== pdfPageNum - 1) return;
    const found = canvas
      .getObjects()
      .find((o) => o.objectNid === payload.objectNid);
    if (!found) return;
    suppressEmit = true;
    suppressUndo = true;
    canvas.remove(found);
    fabric.util.enlivenObjects([payload.json], (objs) => {
      const n = objs[0];
      if (n) {
        if (!n.objectNid) n.set({ objectNid: payload.objectNid });
        canvas.add(n);
      }
      suppressEmit = false;
      suppressUndo = false;
      canvas.renderAll();
      renderTotals();
    });
  });

  socket.on('object:remove', (payload) => {
    if (payload.from === mySocketId) return;
    if (payload.page !== pdfPageNum - 1) return;
    const found = canvas
      .getObjects()
      .find((o) => o.objectNid === payload.objectNid);
    if (found) {
      suppressEmit = true;
      suppressUndo = true;
      canvas.remove(found);
      suppressEmit = false;
      suppressUndo = false;
      canvas.renderAll();
      renderTotals();
    }
  });
}

async function renderPdfPage(num) {
  if (!pdfDoc) return;
  const page = await pdfDoc.getPage(num);
  const base = pdfScale;
  const viewport = page.getViewport({ scale: base });
  const pdfLayer = document.getElementById('pdf-layer');
  pdfLayer.innerHTML = '';
  const pdfCanvas = document.createElement('canvas');
  const ctx = pdfCanvas.getContext('2d');
  pdfCanvas.width = viewport.width;
  pdfCanvas.height = viewport.height;
  pdfLayer.style.width = `${viewport.width}px`;
  pdfLayer.style.height = `${viewport.height}px`;
  pdfLayer.appendChild(pdfCanvas);
  await page.render({ canvasContext: ctx, viewport }).promise;

  canvas.setWidth(viewport.width);
  canvas.setHeight(viewport.height);
  canvas.calcOffset();
  loadPageState();
  setStatus(`Page ${num} / ${pdfDoc.numPages}`);
}

async function loadPdf(file) {
  const buf = await file.arrayBuffer();
  pdfDoc = await pdfjsLib.getDocument({ data: buf }).promise;
  pdfPageNum = 1;
  const sel = document.getElementById('page-select');
  sel.innerHTML = '';
  for (let i = 1; i <= pdfDoc.numPages; i++) {
    const o = document.createElement('option');
    o.value = String(i);
    o.textContent = `Page ${i}`;
    sel.appendChild(o);
  }
  sel.disabled = false;
  document.getElementById('btn-prev').disabled = false;
  document.getElementById('btn-next').disabled = false;
  sel.value = '1';
  await renderPdfPage(1);
}

function wireUi() {
  document.getElementById('pdf-input').addEventListener('change', (ev) => {
    const f = ev.target.files?.[0];
    if (f) loadPdf(f);
  });

  document.getElementById('page-select').addEventListener('change', (ev) => {
    savePageState();
    pdfPageNum = parseInt(ev.target.value, 10) || 1;
    renderPdfPage(pdfPageNum);
  });
  document.getElementById('btn-prev').addEventListener('click', () => {
    if (pdfPageNum <= 1) return;
    savePageState();
    pdfPageNum -= 1;
    document.getElementById('page-select').value = String(pdfPageNum);
    renderPdfPage(pdfPageNum);
  });
  document.getElementById('btn-next').addEventListener('click', () => {
    if (!pdfDoc || pdfPageNum >= pdfDoc.numPages) return;
    savePageState();
    pdfPageNum += 1;
    document.getElementById('page-select').value = String(pdfPageNum);
    renderPdfPage(pdfPageNum);
  });

  document.querySelectorAll('.tool').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tool').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      tool = btn.dataset.tool;
      drawState = null;
      canvas.selection = tool === 'select';
      canvas.defaultCursor = tool === 'pan' ? 'grab' : 'crosshair';
      canvas.forEachObject((o) => {
        o.selectable = tool === 'select';
        o.evented = tool === 'select' || tool === 'pan';
      });
      if (tool === 'pan') {
        canvas.selection = false;
        canvas.forEachObject((o) => {
          o.selectable = false;
          o.evented = false;
        });
      }
      canvas.renderAll();
    });
  });

  let panning = false;
  let lastX = 0;
  let lastY = 0;
  canvas.on('mouse:down', (opt) => {
    if (tool !== 'pan') return;
    panning = true;
    lastX = opt.e.clientX;
    lastY = opt.e.clientY;
    canvas.defaultCursor = 'grabbing';
  });
  canvas.on('mouse:up', () => {
    panning = false;
    if (tool === 'pan') canvas.defaultCursor = 'grab';
  });
  canvas.on('mouse:move', (opt) => {
    if (!panning || tool !== 'pan') return;
    const e = opt.e;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
    const v = canvas.viewportTransform;
    v[4] += dx;
    v[5] += dy;
    canvas.requestRenderAll();
    const pdfCv = document.querySelector('#pdf-layer canvas');
    if (pdfCv) {
      pdfCv.style.transform = `translate(${v[4]}px, ${v[5]}px) scale(${v[0]})`;
      pdfCv.style.transformOrigin = '0 0';
    }
  });

  function zoomAt(center, factor) {
    let z = canvas.getZoom() * factor;
    z = Math.min(6, Math.max(0.15, z));
    const pt = new fabric.Point(
      center?.x ?? canvas.width / 2,
      center?.y ?? canvas.height / 2
    );
    canvas.zoomToPoint(pt, z);
    syncPdfTransform();
    updateZoomLabel();
  }

  function syncPdfTransform() {
    const v = canvas.viewportTransform;
    const pdfCv = document.querySelector('#pdf-layer canvas');
    if (pdfCv) {
      pdfCv.style.transform = `translate(${v[4]}px, ${v[5]}px) scale(${v[0]})`;
      pdfCv.style.transformOrigin = '0 0';
    }
  }

  document.getElementById('btn-zoom-in').addEventListener('click', () => zoomAt(null, 1.15));
  document.getElementById('btn-zoom-out').addEventListener('click', () => zoomAt(null, 1 / 1.15));
  document.getElementById('btn-fit').addEventListener('click', () => {
    canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    syncPdfTransform();
    updateZoomLabel();
  });

  canvas.on('mouse:wheel', (opt) => {
    const delta = opt.e.deltaY;
    let zoom = canvas.getZoom();
    zoom *= 0.999 ** delta;
    zoom = Math.min(6, Math.max(0.15, zoom));
    canvas.zoomToPoint({ x: opt.e.offsetX, y: opt.e.offsetY }, zoom);
    opt.e.preventDefault();
    opt.e.stopPropagation();
    syncPdfTransform();
    updateZoomLabel();
  });

  document.getElementById('btn-undo').addEventListener('click', undo);
  document.getElementById('btn-redo').addEventListener('click', redo);

  document.getElementById('scale-px-per-ft').addEventListener('input', () => {
    renderTotals();
  });

  canvas.on('object:modified', (e) => {
    pushUndoState();
    emitModify(e.target);
    renderTotals();
  });

  canvas.on('object:added', (e) => {
    if (!e.target.objectNid) e.target.set({ objectNid: nid() });
  });

  canvas.on('selection:created', () => {});
  canvas.on('object:removed', (e) => {
    pushUndoState();
    emitRemove(e.target);
    renderTotals();
  });

  document.addEventListener('keydown', (ev) => {
    if (ev.ctrlKey && ev.key === 'z') {
      ev.preventDefault();
      undo();
    }
    if (ev.ctrlKey && (ev.key === 'y' || ev.key === 'Y')) {
      ev.preventDefault();
      redo();
    }
    if (ev.key === 'Enter' && tool === 'polygon') finishPolygon();
    if (ev.key === 'Enter' && tool === 'polyline') finishPolyline();
    if (
      (ev.key === 'Delete' || ev.key === 'Backspace') &&
      !ev.ctrlKey &&
      document.activeElement?.tagName !== 'INPUT' &&
      document.activeElement?.tagName !== 'SELECT' &&
      document.activeElement?.tagName !== 'TEXTAREA'
    ) {
      const act = canvas.getActiveObjects();
      if (act.length && tool === 'select') {
        ev.preventDefault();
        act.forEach((o) => canvas.remove(o));
        canvas.discardActiveObject();
        canvas.requestRenderAll();
      }
    }
    const map = { v: 'select', h: 'pan', l: 'line', p: 'polyline', g: 'polygon', a: 'arc', c: 'count' };
    const k = ev.key.toLowerCase();
    if (!ev.ctrlKey && map[k]) {
      document.querySelector(`[data-tool="${map[k]}"]`)?.click();
    }
  });

  document.getElementById('btn-add-layer').addEventListener('click', () => {
    const name = prompt('Layer name');
    if (!name) return;
    const id = name.toLowerCase().replace(/\s+/g, '-') + '-' + nid().slice(-4);
    const kind = prompt('Kind: linear, area, or count', 'linear') || 'linear';
    layers.push({
      id,
      name,
      color: '#' + Math.floor(Math.random() * 0xffffff).toString(16).padStart(6, '0'),
      kind,
    });
    if (!activeLayerId || !layers.some((l) => l.id === activeLayerId)) {
      activeLayerId = id;
    }
    saveLayers();
    renderLayerList();
  });

  document.getElementById('btn-save-assembly').addEventListener('click', () => {
    const name = document.getElementById('asm-name').value.trim();
    const heightFt = parseFloat(document.getElementById('asm-height').value);
    const note = document.getElementById('asm-note').value.trim();
    if (!name) return;
    assemblies.push({
      id: nid(),
      name,
      heightFt: Number.isFinite(heightFt) ? heightFt : 8,
      note,
    });
    document.getElementById('asm-name').value = '';
    saveAssemblies();
    renderAssembliesList();
    renderLayerList();
  });

  document.getElementById('btn-apply-assembly').addEventListener('click', () => {
    const id = document.getElementById('assembly-apply').value;
    const asm = assemblies.find((a) => a.id === id);
    const sel = canvas.getActiveObject();
    if (!asm || !sel) {
      setStatus('Select a line/polyline and choose an assembly');
      return;
    }
    sel.set({ assemblyId: asm.id });
    canvas.requestRenderAll();
    renderTotals();
    setStatus(`Applied “${asm.name}”`);
  });

  document.getElementById('btn-export-csv').addEventListener('click', exportCsv);
  document.getElementById('btn-export-xlsx').addEventListener('click', exportXlsx);
  document.getElementById('btn-bot-scan').addEventListener('click', runBotScan);
  document.getElementById('btn-voice').addEventListener('click', speakTotals);
}

function renderAssembliesList() {
  const el = document.getElementById('assemblies');
  el.innerHTML = assemblies
    .map(
      (a) =>
        `<div class="asm-item"><strong>${escapeHtml(a.name)}</strong> — ${a.heightFt}′ ${escapeHtml(a.note || '')}</div>`
    )
    .join('');
}

function exportRows() {
  const rows = [];
  const pageLabel = pdfDoc ? pdfPageNum : 1;
  canvas.getObjects().forEach((o) => {
    if (o.isBot) return;
    const L = layerById(o.takeoffLayerId);
    const kind = o.takeoffKind || L.kind;
    let qty = '';
    let unit = '';
    if (kind === 'count') {
      qty = '1';
      unit = 'count';
    } else if (o.type === 'line') {
      const len = fabricLineLengthPx(o);
      qty = ftFromPx(len).toFixed(2);
      unit = 'lf';
    } else if (o.type === 'polyline' && o.points) {
      let len = 0;
      for (let i = 1; i < o.points.length; i++) {
        len += Math.hypot(
          o.points[i].x - o.points[i - 1].x,
          o.points[i].y - o.points[i - 1].y
        );
      }
      qty = ftFromPx(len).toFixed(2);
      unit = 'lf';
    } else if (o.type === 'polygon') {
      const pts = polygonAbsolutePoints(o);
      if (kind === 'area' && pts.length >= 3) {
        qty = sqFtFromPxArea(polygonAreaPx(pts)).toFixed(2);
        unit = 'sf';
      } else {
        let len = 0;
        for (let i = 0; i < pts.length; i++) {
          const j = (i + 1) % pts.length;
          len += Math.hypot(pts[j].x - pts[i].x, pts[j].y - pts[i].y);
        }
        qty = ftFromPx(len).toFixed(2);
        unit = 'lf';
      }
    } else if (o.type === 'path') {
      qty = ftFromPx(pathLengthApprox(o)).toFixed(2);
      unit = 'lf';
    } else if (o.type === 'circle') {
      qty = '1';
      unit = 'count';
    }
    const rateKey = o.takeoffLayerId;
    const rate = parseFloat(rates[rateKey] ?? rates[L.id]);
    const qn = parseFloat(qty);
    const cost =
      Number.isFinite(rate) && Number.isFinite(qn) ? (qn * rate).toFixed(2) : '';
    rows.push({
      page: pageLabel,
      type: L.name,
      quantity: qty,
      unit,
      rate: Number.isFinite(rate) ? String(rate) : '',
      cost,
      assembly: o.assemblyId
        ? assemblies.find((a) => a.id === o.assemblyId)?.name || ''
        : '',
    });
  });

  return rows;
}

function exportCsv() {
  const rows = exportRows();
  const header = ['page', 'type', 'quantity', 'unit', 'rate', 'cost', 'assembly'];
  const lines = [header.join(',')].concat(
    rows.map((r) =>
      header
        .map((h) => {
          const v = r[h] ?? '';
          const s = String(v).replace(/"/g, '""');
          return /[",\n]/.test(s) ? `"${s}"` : s;
        })
        .join(',')
    )
  );
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'takeoff-export.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}

function exportXlsx() {
  if (typeof XLSX === 'undefined') {
    alert('SheetJS not loaded');
    return;
  }
  const rows = exportRows();
  const ws = XLSX.utils.json_to_sheet(rows);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Takeoff');
  const acc = computeTotals();
  const summary = [];
  Object.keys(acc).forEach((key) => {
    const { linearFt, sqFt, count, layer } = acc[key];
    const rate = parseFloat(rates[key] ?? rates[layer.id]);
    if (linearFt < 0.001 && sqFt < 0.001 && count === 0) return;
    if (linearFt > 0.001) {
      const cost = Number.isFinite(rate) ? linearFt * rate : '';
      summary.push({
        type: layer.name,
        metric: 'linear_ft',
        quantity: linearFt,
        rate: Number.isFinite(rate) ? rate : '',
        cost: cost === '' ? '' : Number(cost.toFixed(2)),
      });
    }
    if (sqFt > 0.001) {
      const cost = Number.isFinite(rate) ? sqFt * rate : '';
      summary.push({
        type: layer.name,
        metric: 'square_ft',
        quantity: sqFt,
        rate: Number.isFinite(rate) ? rate : '',
        cost: cost === '' ? '' : Number(cost.toFixed(2)),
      });
    }
    if (count > 0) {
      const cost = Number.isFinite(rate) ? count * rate : '';
      summary.push({
        type: layer.name,
        metric: 'count',
        quantity: count,
        rate: Number.isFinite(rate) ? rate : '',
        cost: cost === '' ? '' : Number(cost.toFixed(2)),
      });
    }
  });
  if (summary.length) {
    XLSX.utils.book_append_sheet(
      wb,
      XLSX.utils.json_to_sheet(summary),
      'Summary'
    );
  }
  XLSX.writeFile(wb, 'takeoff-export.xlsx');
}

function getPdfImageData() {
  const pdfCv = document.querySelector('#pdf-layer canvas');
  if (!pdfCv) return null;
  const ctx = pdfCv.getContext('2d');
  return ctx.getImageData(0, 0, pdfCv.width, pdfCv.height);
}

function runBotScan() {
  const img = getPdfImageData();
  if (!img) {
    setStatus('Load a PDF first');
    return;
  }
  const w = img.width;
  const h = img.height;
  const step = 4;
  const cols = Math.ceil(w / step);
  const rows = Math.ceil(h / step);
  const gray = new Float32Array(cols * rows);
  for (let yi = 0; yi < rows; yi++) {
    for (let xi = 0; xi < cols; xi++) {
      const x = Math.min(xi * step, w - 1);
      const y = Math.min(yi * step, h - 1);
      const i = (y * w + x) * 4;
      gray[yi * cols + xi] =
        (img.data[i] + img.data[i + 1] + img.data[i + 2]) / 3;
    }
  }
  const mag = new Float32Array(cols * rows);
  for (let y = 1; y < rows - 1; y++) {
    for (let x = 1; x < cols - 1; x++) {
      const i = y * cols + x;
      const gx =
        -gray[i - cols - 1] +
        gray[i - cols + 1] +
        -2 * gray[i - 1] +
        2 * gray[i + 1] +
        -gray[i + cols - 1] +
        gray[i + cols + 1];
      const gy =
        -gray[i - cols - 1] -
        2 * gray[i - cols] -
        gray[i - cols + 1] +
        gray[i + cols - 1] +
        2 * gray[i + cols] +
        gray[i + cols + 1];
      mag[i] = Math.hypot(gx, gy);
    }
  }
  let maxM = 0;
  for (let i = 0; i < mag.length; i++) if (mag[i] > maxM) maxM = mag[i];
  const thr = maxM * 0.35;

  const suggestions = [];
  const scanRow = (yy) => {
    let runStart = -1;
    for (let x = 0; x < cols; x++) {
      const on = mag[yy * cols + x] >= thr;
      if (on && runStart < 0) runStart = x;
      if (!on && runStart >= 0) {
        const runLen = (x - runStart) * step;
        if (runLen > w * 0.15) {
          const x1 = runStart * step;
          const x2 = x * step;
          const yp = yy * step;
          suggestions.push({
            kind: 'wall',
            x1,
            y1: yp,
            x2,
            y2: yp,
            ft: ftFromPx(x2 - x1),
          });
        }
        runStart = -1;
      }
    }
  };
  for (let y = 2; y < rows - 2; y += 3) scanRow(y);

  if (!suggestions.length) {
    setStatus('Bot: no strong edges found — try a sharper scan or zoom');
    return;
  }
  const best = suggestions.sort((a, b) => b.ft - a.ft)[0];
  showBotToast(best);
}

function showBotToast(seg) {
  const el = document.getElementById('bot-toast');
  el.hidden = false;
  el.innerHTML = `
    <p>I see about <strong>${seg.ft.toFixed(1)} ft</strong> along a straight edge — add as a dashed suggestion?</p>
    <div class="bot-actions">
      <button type="button" class="primary" id="bot-add">Add</button>
      <button type="button" id="bot-ignore">Ignore</button>
    </div>
  `;
  const close = () => {
    el.hidden = true;
  };
  el.querySelector('#bot-ignore').onclick = close;
  el.querySelector('#bot-add').onclick = () => {
    const ln = new fabric.Line([seg.x1, seg.y1, seg.x2, seg.y2], {});
    ln.set({
      stroke: '#f59e0b',
      strokeWidth: 2,
      fill: 'transparent',
      strokeDashArray: [8, 6],
      opacity: 0.85,
      takeoffLayerId: null,
      takeoffKind: 'linear',
      objectNid: nid(),
      isBot: true,
    });
    canvas.add(ln);
    pushUndoState();
    emitAdd(ln);
    renderTotals();
    close();
    setStatus('Bot suggestion added (not in totals)');
  };
}

async function speakTotals() {
  const acc = computeTotals();
  const parts = [];
  Object.keys(acc).forEach((key) => {
    const { linearFt, sqFt, count, layer } = acc[key];
    if (layer.name.includes('assembly')) return;
    if (linearFt > 0.01) parts.push(`${layer.name}: ${Math.round(linearFt)} linear feet`);
    if (sqFt > 0.01) parts.push(`${layer.name}: ${Math.round(sqFt)} square feet`);
    if (count > 0) parts.push(`${layer.name}: ${count} items`);
  });
  const text = parts.length ? parts.join('. ') + '.' : 'No totals yet.';
  try {
    const res = await fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      setStatus(j.error || `Voice failed (${res.status})`);
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.play();
    audio.onended = () => URL.revokeObjectURL(url);
    setStatus('Playing voice totals…');
  } catch (e) {
    setStatus(String(e.message || e));
  }
}

function initCanvas() {
  canvas = new fabric.Canvas('c', {
    selection: true,
    preserveObjectStacking: true,
    backgroundColor: 'transparent',
  });
  fabric.Object.prototype.set({
    transparentCorners: false,
    cornerColor: '#58a6ff',
    borderColor: '#58a6ff',
  });
  attachDrawingHandlers();
  wireUi();
  wireCollab();

  updateZoomLabel();
  undoStack.length = 0;
  redoStack.length = 0;
  pushUndoState();
}

renderLayerList();
renderAssembliesList();
initCanvas();
