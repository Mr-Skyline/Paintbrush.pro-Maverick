import { useEffect, useMemo, useRef, useState } from 'react';
import { createSeedPopulation } from '@/battleship/wallhunt/policies';
import { defaultWallHuntMaps } from '@/battleship/wallhunt/sampleMaps';
import { runWallTournament } from '@/battleship/wallhunt/tournament';
import { evaluateQualification } from '@/battleship/wallhunt/qualification';
import {
  ensureTrainingProfile,
  saveActiveTrainingProfileId,
  saveTrainingTemplateForResolution,
  updateTrainingProfile,
  withClampedProfile,
  type WallTrainingProfile,
} from '@/battleship/wallhunt/trainingProfiles';
import {
  loadActiveOstButtonProfileName,
  loadOstButtonProfiles,
  resetOstButtons,
  saveActiveOstButtonProfileName,
  saveOstButtonProfiles,
  saveOstButtons,
  type OstButtonProfile,
} from '@/battleship/wallhunt/ostButtons';
import type {
  OstButtonTarget,
  QualificationMode,
  QualificationResult,
  Rect2D,
  TournamentResult,
  UiClickableZone,
  WallInteractionPolicy,
  WallEpisodeResult,
  WallHuntAgent,
  WallHuntMap,
} from '@/battleship/wallhunt/types';

const CALIBRATION_AGENT_ID = 'calibration-probe';

const downloadText = (filename: string, content: string, mime = 'text/plain'): void => {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
};

const readJsonFile = async <T,>(file: File): Promise<T> => {
  const raw = await file.text();
  return JSON.parse(raw) as T;
};

const readDataUrlFile = async (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('Could not read image file.'));
    reader.readAsDataURL(file);
  });

const toScreen = (
  map: WallHuntMap,
  x: number,
  y: number,
  width: number,
  height: number
): { x: number; y: number } => ({
  x: (x / Math.max(1, map.width)) * width,
  y: (y / Math.max(1, map.height)) * height,
});

const clampRect = (rect: Rect2D, map: WallHuntMap): Rect2D => {
  const x = Math.max(0, Math.min(map.width - 1, Math.round(rect.x)));
  const y = Math.max(0, Math.min(map.height - 1, Math.round(rect.y)));
  const maxW = Math.max(1, map.width - x);
  const maxH = Math.max(1, map.height - y);
  return {
    x,
    y,
    width: Math.max(1, Math.min(maxW, Math.round(rect.width))),
    height: Math.max(1, Math.min(maxH, Math.round(rect.height))),
  };
};

const buildCalibrationProbeAgent = (clickSigma: number): WallHuntAgent => ({
  id: CALIBRATION_AGENT_ID,
  generation: 0,
  weights: {
    precision: 1,
    clickSigma: Math.max(0, clickSigma),
    exploration: 0,
    longJumpBias: 1,
  },
  proposeNextPoint: () => ({ x: 0, y: 0 }),
  clone: () => buildCalibrationProbeAgent(clickSigma),
});

const leaderboardHtml = (result: TournamentResult): string => {
  const rows = result.rounds
    .map((round) => {
      const body = round.leaderboard
        .map(
          (r) =>
            `<tr><td>${r.agentId}</td><td>${r.score.toFixed(1)}</td><td>${r.completedWalls}</td><td>${r.segmentsTotal}</td><td>${r.qualificationPass ? 'pass' : 'fail'}</td></tr>`
        )
        .join('');
      return `<h3>Round ${round.round}</h3><div>Winners: ${round.winners.join(', ') || 'none'}</div><table><thead><tr><th>Agent</th><th>Score</th><th>Walls</th><th>Segs</th><th>Q</th></tr></thead><tbody>${body}</tbody></table>`;
    })
    .join('');
  return `<!doctype html><html><head><meta charset="utf-8"/><title>Wall Battleship Leaderboard</title><style>
body{font-family:Segoe UI,Arial,sans-serif;background:#0f172a;color:#e2e8f0;padding:12px}
h1{font-size:18px;margin:0 0 12px} h3{margin:16px 0 6px;font-size:15px}
table{width:100%;border-collapse:collapse;margin-top:6px;font-size:12px}
th,td{border:1px solid #334155;padding:6px;text-align:left}
thead{background:#1e293b}
</style></head><body>
<h1>Wall Battleship Leaderboard (${result.mode})</h1>
${rows || '<div>No rounds yet.</div>'}
</body></html>`;
};

const controlsWindowHtml = (opts: {
  mode: QualificationMode;
  rounds: number;
  populationSize: number;
  winnersPerRound: number;
  isRunning: boolean;
  ingestingImage: boolean;
  mapImageLabel: string;
  monitorPreference: string;
  displayOptions: Array<{ value: string; label: string }>;
  result: TournamentResult | null;
  interactionPolicy: WallInteractionPolicy;
  arenaRect: Rect2D;
  uiZoneCount: number;
  profileId: string;
}): string => {
  const commandBusKey = 'wall-battleship-control-command-v1';
  const latestRound = opts.result?.rounds[opts.result.rounds.length - 1] ?? null;
  const resultRows =
    latestRound?.leaderboard
      .slice(0, 10)
      .map(
        (r) =>
          `<tr><td>${r.agentId}</td><td>${r.score.toFixed(1)}</td><td>${r.completedWalls}</td><td>${r.segmentsTotal}</td><td>${r.invalidActions ?? 0}</td><td>${r.qualificationPass ? 'pass' : 'fail'}</td></tr>`
      )
      .join('') ?? '';
  const monitorOptions = opts.displayOptions
    .map(
      (opt) =>
        `<option value="${opt.value}" ${opt.value === opts.monitorPreference ? 'selected' : ''}>${opt.label}</option>`
    )
    .join('');
  return `<!doctype html><html><head><meta charset="utf-8"/><title>Wall Battleship Controls</title><style>
body{font-family:Segoe UI,Arial,sans-serif;background:#020617;color:#e2e8f0;padding:12px;margin:0}
h1{font-size:16px;margin:0 0 10px}
h2{font-size:13px;margin:12px 0 6px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
label{font-size:12px;display:flex;flex-direction:column;gap:4px}
input,select,button{background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:6px 8px;font-size:12px}
button{cursor:pointer}
.row{display:flex;gap:8px;flex-wrap:wrap}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{border:1px solid #334155;padding:5px;text-align:left}
thead{background:#1e293b}
.muted{color:#94a3b8;font-size:11px}
</style></head><body>
<h1>Wall Battleship Controls</h1>
<div id="bridgeStatus" class="muted">Bridge: checking...</div>
<div class="grid">
  <label>Mode<select id="mode"><option value="warmup" ${opts.mode === 'warmup' ? 'selected' : ''}>warmup</option><option value="ranked" ${opts.mode === 'ranked' ? 'selected' : ''}>ranked</option></select></label>
  <label>Rounds<input id="rounds" type="number" min="1" value="${opts.rounds}" /></label>
  <label>Population<input id="population" type="number" min="4" value="${opts.populationSize}" /></label>
  <label>Winners<input id="winners" type="number" min="1" value="${opts.winnersPerRound}" /></label>
  <label style="grid-column:1 / span 2;">Interaction policy
    <select id="policy">
      <option value="buttons-only" ${opts.interactionPolicy === 'buttons-only' ? 'selected' : ''}>buttons-only</option>
      <option value="annotated-ui" ${opts.interactionPolicy === 'annotated-ui' ? 'selected' : ''}>annotated-ui</option>
      <option value="strict-no-ui" ${opts.interactionPolicy === 'strict-no-ui' ? 'selected' : ''}>strict-no-ui</option>
    </select>
  </label>
  <label style="grid-column:1 / span 2;">Target monitor<select id="monitor">${monitorOptions}</select></label>
</div>
<div class="row" style="margin-top:8px">
  <button id="run">${opts.isRunning ? 'Running...' : 'Run tournament'}</button>
  <button id="loadMap">${opts.ingestingImage ? 'Parsing...' : 'Load selected image'}</button>
  <button id="leaderboard">Leaderboard window</button>
  <button id="fullscreen">Toggle fullscreen</button>
  <button id="monitorApply">Apply monitor</button>
</div>
<div class="row" style="margin-top:8px">
  <button id="winnersJson">Winners JSON</button>
  <button id="losersJson">Losers JSON</button>
  <button id="reportMd">Report MD</button>
</div>
<div class="row" style="margin-top:8px">
  <button id="startArenaEdit">Draw arena (2 clicks)</button>
  <button id="startZoneEdit">Add UI zone (2 clicks)</button>
  <button id="clearZones">Clear UI zones</button>
  <button id="saveTemplate">Save resolution template</button>
</div>
<div style="margin-top:10px;border:1px solid #334155;border-radius:8px;padding:8px;">
  <div style="font-size:12px;margin-bottom:6px;">Wall map image upload</div>
  <input id="mapFileInput" type="file" accept="image/png,image/jpeg,image/jpg,image/webp,image/gif,image/bmp" />
  <div id="mapFileName" class="muted" style="margin-top:4px;">Selected file: none</div>
</div>
<div class="muted" style="margin-top:8px">Map image: ${opts.mapImageLabel}. Profile: ${opts.profileId || 'none'}. Warm-up gate: 7/10, ranked: 10/10.</div>
<div class="muted">Arena: x=${Math.round(opts.arenaRect.x)}, y=${Math.round(opts.arenaRect.y)}, w=${Math.round(opts.arenaRect.width)}, h=${Math.round(opts.arenaRect.height)} | UI zones: ${opts.uiZoneCount}</div>
<h2>Tournament results</h2>
<div class="muted">Final winners: ${opts.result?.finalWinnerIds.join(', ') || 'none yet'}</div>
${latestRound ? `<div class="muted">Latest round: ${latestRound.round} | winners: ${latestRound.winners.join(', ') || 'none'}</div>` : '<div class="muted">No rounds yet.</div>'}
${latestRound ? `<div class="muted">Invalid actions (top): ${latestRound.leaderboard.slice(0,5).map(r=>`${r.agentId}:${r.invalidActions ?? 0}`).join(' | ')}</div>` : ''}
${latestRound ? `<table><thead><tr><th>Agent</th><th>Score</th><th>Walls</th><th>Segs</th><th>Invalid</th><th>Q</th></tr></thead><tbody>${resultRows}</tbody></table>` : ''}
<script>
(()=>{
const commandBusKey='${commandBusKey}';
const send=(type,payload={})=>{
  const msg = {source:'wall-controls',type,value:payload.value};
  try {
    localStorage.setItem(commandBusKey, JSON.stringify({...msg, ts: Date.now()}));
  } catch {}
  try {
    if (window.desktopApi && typeof window.desktopApi.sendWallControl === 'function') {
      window.desktopApi.sendWallControl(msg);
    }
  } catch {}
  try {
    if (window.BroadcastChannel) {
      const bc = new BroadcastChannel('wall-battleship-controls');
      bc.postMessage(msg);
      bc.close();
    }
  } catch {}
  try {
    if (window.opener) {
      const bridge = window.opener.__wallBattleshipControlBridge;
      if (bridge && typeof bridge[type] === 'function') {
        bridge[type](payload.value);
      } else {
        window.opener.postMessage({source:'wall-controls',type,...payload},'*');
      }
    }
  } catch {}
};
const byId=(id)=>document.getElementById(id);
const on=(id,evt,fn)=>{ const el = byId(id); if (el) el.addEventListener(evt,fn); };
const statusEl = byId('bridgeStatus');
if (statusEl) {
  const hasDesktopApi = !!(window.desktopApi && typeof window.desktopApi.sendWallControl === 'function');
  const hasOpener = !!window.opener;
  statusEl.textContent = 'Bridge: desktopApi=' + (hasDesktopApi ? 'yes' : 'no') + ', opener=' + (hasOpener ? 'yes' : 'no');
}
on('mode','change',(e)=>send('setMode',{value:e.target.value}));
on('rounds','change',(e)=>send('setRounds',{value:Number(e.target.value)}));
on('population','change',(e)=>send('setPopulation',{value:Number(e.target.value)}));
on('winners','change',(e)=>send('setWinners',{value:Number(e.target.value)}));
on('policy','change',(e)=>send('setPolicy',{value:e.target.value}));
on('monitor','change',(e)=>send('setMonitorPref',{value:e.target.value}));
on('run','click',()=>send('run'));
on('loadMap','click',()=>{
  const input = byId('mapFileInput');
  const f = input && input.files && input.files[0];
  if (!f) {
    alert('Choose an image file in "Wall map image upload" first.');
    return;
  }
  const reader = new FileReader();
  reader.onload = ()=>{
    send('loadMapDataUrl',{value:{dataUrl:String(reader.result||''),fileName:f.name}});
  };
  reader.onerror = ()=>alert('Could not read image file.');
  reader.readAsDataURL(f);
});
on('mapFileInput','change',()=>{
  const input = byId('mapFileInput');
  const f = input && input.files && input.files[0];
  const nameEl = byId('mapFileName');
  if (nameEl) nameEl.textContent = f ? ('Selected file: ' + f.name) : 'Selected file: none';
  if (!f) return;
  const reader = new FileReader();
  reader.onload = ()=>{
    send('loadMapDataUrl',{value:{dataUrl:String(reader.result||''),fileName:f.name}});
  };
  reader.onerror = ()=>alert('Could not read image file.');
  reader.readAsDataURL(f);
});
on('leaderboard','click',()=>send('leaderboard'));
on('fullscreen','click',()=>send('fullscreen'));
on('monitorApply','click',()=>send('applyMonitor'));
on('winnersJson','click',()=>send('winnersJson'));
on('losersJson','click',()=>send('losersJson'));
on('reportMd','click',()=>send('reportMd'));
on('startArenaEdit','click',()=>send('startArenaEdit'));
on('startZoneEdit','click',()=>send('startZoneEdit'));
on('clearZones','click',()=>send('clearZones'));
on('saveTemplate','click',()=>send('saveTemplate'));
})();
</script>
</body></html>`;
};

const loadImageData = async (
  src: string
): Promise<{ width: number; height: number; data: Uint8ClampedArray }> =>
  new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('Could not create canvas context.'));
        return;
      }
      ctx.drawImage(img, 0, 0);
      const imageData = ctx.getImageData(0, 0, img.width, img.height);
      resolve({
        width: img.width,
        height: img.height,
        data: imageData.data,
      });
    };
    img.onerror = () => reject(new Error(`Failed loading image: ${src}`));
    img.src = src;
  });

const isRedPixel = (r: number, g: number, b: number): boolean =>
  r >= 160 && g <= 95 && b <= 95 && r - Math.max(g, b) >= 45;

const extractRedComponents = (
  width: number,
  height: number,
  data: Uint8ClampedArray
): Array<{
  pixels: Array<{ x: number; y: number }>;
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
  cx: number;
  cy: number;
}> => {
  const mask = new Uint8Array(width * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const idx = (y * width + x) * 4;
      if (isRedPixel(data[idx], data[idx + 1], data[idx + 2])) {
        mask[y * width + x] = 1;
      }
    }
  }

  const visited = new Uint8Array(width * height);
  const out: Array<{
    pixels: Array<{ x: number; y: number }>;
    minX: number;
    minY: number;
    maxX: number;
    maxY: number;
    cx: number;
    cy: number;
  }> = [];

  const dirs = [
    [1, 0],
    [-1, 0],
    [0, 1],
    [0, -1],
    [1, 1],
    [1, -1],
    [-1, 1],
    [-1, -1],
  ];

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const start = y * width + x;
      if (!mask[start] || visited[start]) continue;
      const queue = [{ x, y }];
      visited[start] = 1;
      const pixels: Array<{ x: number; y: number }> = [];
      let minX = x;
      let minY = y;
      let maxX = x;
      let maxY = y;
      let sumX = 0;
      let sumY = 0;
      while (queue.length > 0) {
        const cur = queue.shift()!;
        pixels.push(cur);
        sumX += cur.x;
        sumY += cur.y;
        if (cur.x < minX) minX = cur.x;
        if (cur.y < minY) minY = cur.y;
        if (cur.x > maxX) maxX = cur.x;
        if (cur.y > maxY) maxY = cur.y;
        for (const [dx, dy] of dirs) {
          const nx = cur.x + dx;
          const ny = cur.y + dy;
          if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
          const ni = ny * width + nx;
          if (!mask[ni] || visited[ni]) continue;
          visited[ni] = 1;
          queue.push({ x: nx, y: ny });
        }
      }
      if (pixels.length < 60) continue;
      out.push({
        pixels,
        minX,
        minY,
        maxX,
        maxY,
        cx: sumX / pixels.length,
        cy: sumY / pixels.length,
      });
    }
  }

  return out.sort((a, b) => a.cy - b.cy);
};

const polylineFromComponent = (component: {
  pixels: Array<{ x: number; y: number }>;
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
  cx: number;
  cy: number;
}): Array<{ x: number; y: number }> => {
  const w = component.maxX - component.minX + 1;
  const h = component.maxY - component.minY + 1;
  if (w / Math.max(1, h) >= 1.45) {
    return [
      { x: component.minX, y: component.cy },
      { x: component.maxX, y: component.cy },
    ];
  }
  if (h / Math.max(1, w) >= 1.45) {
    return [
      { x: component.cx, y: component.minY },
      { x: component.cx, y: component.maxY },
    ];
  }
  return [
    { x: component.minX, y: component.minY },
    { x: component.maxX, y: component.minY },
    { x: component.maxX, y: component.maxY },
    { x: component.minX, y: component.maxY },
    { x: component.minX, y: component.minY },
  ];
};

const inferSegmentCapsFromConditionsRegion = async (
  src: string,
  expectedCount: number
): Promise<number[]> => {
  try {
    const img = await loadImageData(src);
    const cropX = Math.floor(img.width * 0.7);
    const cropW = img.width - cropX;
    const canvas = document.createElement('canvas');
    canvas.width = cropW;
    canvas.height = img.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return Array.from({ length: expectedCount }, () => 8);
    const tmp = document.createElement('canvas');
    tmp.width = img.width;
    tmp.height = img.height;
    const tctx = tmp.getContext('2d');
    if (!tctx) return Array.from({ length: expectedCount }, () => 8);
    const id = new ImageData(img.data, img.width, img.height);
    tctx.putImageData(id, 0, 0);
    ctx.drawImage(tmp, cropX, 0, cropW, img.height, 0, 0, cropW, img.height);

    const tesseract = await import('tesseract.js');
    const out = await tesseract.recognize(canvas, 'eng');
    const nums = (out.data.text.match(/\d{1,2}/g) ?? [])
      .map((n) => Number(n))
      .filter((n) => Number.isFinite(n) && n >= 1 && n <= 40);
    if (nums.length === 0) return Array.from({ length: expectedCount }, () => 8);
    return Array.from({ length: expectedCount }, (_, i) => nums[i] ?? nums[nums.length - 1] ?? 8);
  } catch {
    return Array.from({ length: expectedCount }, () => 8);
  }
};

const mapFromRedWallsImage = async (src: string): Promise<WallHuntMap> => {
  const img = await loadImageData(src);
  const components = extractRedComponents(img.width, img.height, img.data);
  const caps = await inferSegmentCapsFromConditionsRegion(src, components.length);
  const walls = components.map((c, idx) => ({
    wallId: `wall-${idx + 1}`,
    className: c.minX < img.width * 0.2 || c.maxX > img.width * 0.8 ? 'perimeter' : 'interior',
    polyline: polylineFromComponent(c),
    tolerancePx: 12,
    maxSegments: caps[idx] ?? 8,
    requiredCoverage: 0.8,
  }));
  return {
    mapId: 'office-space-battleship',
    width: img.width,
    height: img.height,
    backgroundUrl: src,
    imagePath: src,
    walls,
  };
};

export function WallBattleshipLab() {
  const [maps, setMaps] = useState<WallHuntMap[]>(() => defaultWallHuntMaps());
  const [mode, setMode] = useState<QualificationMode>('warmup');
  const [rounds, setRounds] = useState(5);
  const [populationSize, setPopulationSize] = useState(12);
  const [winnersPerRound, setWinnersPerRound] = useState(4);
  const [mutationRate] = useState(0.35);
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<TournamentResult | null>(null);
  const [reportMd, setReportMd] = useState('');
  const [selectedEpisodeKey, setSelectedEpisodeKey] = useState('');
  const [step, setStep] = useState(1);
  const [ingestingImage, setIngestingImage] = useState(false);
  const [mapImageLabel, setMapImageLabel] = useState('none');
  const [ostScaleMode, setOstScaleMode] = useState(true);
  const [replayFullscreen, setReplayFullscreen] = useState(false);
  const [overlayTop, setOverlayTop] = useState(52);
  const [overlayLeft, setOverlayLeft] = useState(260);
  const [overlayWidth, setOverlayWidth] = useState(320);
  const [showCalibration, setShowCalibration] = useState(false);
  const [trainingProfile, setTrainingProfile] = useState<WallTrainingProfile | null>(null);
  const [interactionPolicy, setInteractionPolicy] = useState<WallInteractionPolicy>('buttons-only');
  const [arenaRect, setArenaRect] = useState<Rect2D>({ x: 100, y: 100, width: 400, height: 400 });
  const [uiClickableZones, setUiClickableZones] = useState<UiClickableZone[]>([]);
  const [editMode, setEditMode] = useState<'none' | 'arena' | 'zone'>('none');
  const [pendingRectStart, setPendingRectStart] = useState<{ x: number; y: number } | null>(null);
  const [buttonProfiles, setButtonProfiles] = useState<OstButtonProfile[]>(() =>
    loadOstButtonProfiles()
  );
  const [activeButtonProfile, setActiveButtonProfile] = useState<string>(() =>
    loadActiveOstButtonProfileName()
  );
  const [buttonTargets, setButtonTargets] = useState<OstButtonTarget[]>(() => {
    const profiles = loadOstButtonProfiles();
    const active = loadActiveOstButtonProfileName();
    return profiles.find((p) => p.name === active)?.buttons ?? profiles[0]?.buttons ?? [];
  });
  const [profileNameDraft, setProfileNameDraft] = useState('');
  const [captureButtonId, setCaptureButtonId] = useState<string | null>(null);
  const [calibrationNoisePx, setCalibrationNoisePx] = useState(2);
  const [qualificationCheck, setQualificationCheck] = useState<QualificationResult | null>(null);
  const [displayOptions, setDisplayOptions] = useState<
    Array<{ value: `id:${number}` | 'primary' | 'secondary'; label: string }>
  >([
    { value: 'primary', label: 'Primary monitor' },
    { value: 'secondary', label: 'Secondary monitor' },
  ]);
  const [monitorPreference, setMonitorPreference] = useState<
    `id:${number}` | 'primary' | 'secondary'
  >('secondary');
  const [applyingMonitorPreference, setApplyingMonitorPreference] = useState(false);
  const [useDetachedControls] = useState(Boolean(window.desktopApi));
  const fullscreenContainerRef = useRef<HTMLDivElement | null>(null);
  const replaySurfaceRef = useRef<HTMLDivElement | null>(null);
  const leaderboardWinRef = useRef<Window | null>(null);
  const controlsWinRef = useRef<Window | null>(null);
  const mapImageInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const activeExists = buttonProfiles.some((p) => p.name === activeButtonProfile);
    if (activeExists) return;
    const fallback = buttonProfiles[0];
    if (!fallback) return;
    setActiveButtonProfile(fallback.name);
    saveActiveOstButtonProfileName(fallback.name);
    setButtonTargets(fallback.buttons);
    saveOstButtons(fallback.buttons);
  }, [activeButtonProfile, buttonProfiles]);

  useEffect(() => {
    const onFsChange = () => {
      setReplayFullscreen(Boolean(document.fullscreenElement));
    };
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
  }, []);

  useEffect(() => {
    const desktopApi = window.desktopApi;
    if (!desktopApi) return;
    void (async () => {
      try {
        const [displays, pref] = await Promise.all([
          desktopApi.listDisplays(),
          desktopApi.getMonitorPreference(),
        ]);
        const nextOptions: Array<{ value: `id:${number}` | 'primary' | 'secondary'; label: string }> = [
          { value: 'primary', label: 'Primary monitor' },
          { value: 'secondary', label: 'Secondary monitor' },
          ...displays.map((d) => ({
            value: `id:${d.id}` as `id:${number}`,
            label: d.label,
          })),
        ];
        const unique = nextOptions.filter(
          (opt, idx, all) => all.findIndex((v) => v.value === opt.value) === idx
        );
        setDisplayOptions(unique);
        if (
          pref === 'primary' ||
          pref === 'secondary' ||
          /^id:\d+$/.test(pref)
        ) {
          setMonitorPreference(pref as `id:${number}` | 'primary' | 'secondary');
        }
      } catch {
        // Leave defaults if desktop monitor APIs are unavailable.
      }
    })();
  }, []);

  useEffect(() => {
    return () => {
      if (leaderboardWinRef.current && !leaderboardWinRef.current.closed) {
        leaderboardWinRef.current.close();
      }
      if (controlsWinRef.current && !controlsWinRef.current.closed) {
        controlsWinRef.current.close();
      }
    };
  }, []);

  const episodes = useMemo(() => {
    if (!result) return [] as WallEpisodeResult[];
    return result.rounds.flatMap((r) => r.episodes);
  }, [result]);

  const selectedEpisode = useMemo(() => {
    if (!selectedEpisodeKey) return episodes[0] ?? null;
    const [agentId, mapId, roundStr] = selectedEpisodeKey.split('|');
    const roundNum = Number(roundStr);
    return (
      result?.rounds
        .find((r) => r.round === roundNum)
        ?.episodes.find((e) => e.agentId === agentId && e.mapId === mapId) ??
      episodes[0] ??
      null
    );
  }, [episodes, result, selectedEpisodeKey]);

  const mapForSelected = useMemo(
    () => maps.find((m) => m.mapId === selectedEpisode?.mapId) ?? maps[0] ?? null,
    [maps, selectedEpisode]
  );

  useEffect(() => {
    const map = maps[0];
    if (!map) return;
    const profile = withClampedProfile(
      ensureTrainingProfile({
        map,
        imageLabel: mapImageLabel,
        fallbackButtons: buttonTargets,
      }),
      map
    );
    setTrainingProfile(profile);
    setInteractionPolicy(profile.interactionPolicy);
    setArenaRect(profile.arenaRect);
    setUiClickableZones(profile.uiClickableZones);
    if (profile.buttonTargets.length > 0) {
      setButtonTargets(profile.buttonTargets);
    }
    saveActiveTrainingProfileId(profile.profileId);
    // Intentionally only reload profile on map/image changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maps[0]?.mapId, mapImageLabel]);

  const runTournament = async (): Promise<void> => {
    setIsRunning(true);
    try {
      const pop = createSeedPopulation(Math.max(4, populationSize));
      const { result: out, reportMarkdown } = runWallTournament({
        maps,
        initialPopulation: pop,
        rounds: Math.max(1, rounds),
        winnersPerRound: Math.max(1, winnersPerRound),
        mode,
        mutationRate: Math.max(0, Math.min(0.95, mutationRate)),
        buttonTargets,
        interactionConfig: {
          arenaRect,
          uiClickableZones,
          buttonTargets,
          policy: interactionPolicy,
        },
      });
      setResult(out);
      setReportMd(reportMarkdown);
      const first = out.rounds[0]?.episodes[0];
      if (first) {
        setSelectedEpisodeKey(`${first.agentId}|${first.mapId}|1`);
        setStep(1);
      }
    } finally {
      setIsRunning(false);
    }
  };

  const parseAndSetMapImage = async (src: string, label: string): Promise<void> => {
    setIngestingImage(true);
    try {
      const parsed = await mapFromRedWallsImage(src);
      setMaps([parsed]);
      setMapImageLabel(label);
      alert(`Loaded "${label}". Extracted ${parsed.walls.length} red wall targets.`);
    } catch (err) {
      alert(`Failed to parse selected image: ${String(err)}`);
    } finally {
      setIngestingImage(false);
    }
  };

  const persistTrainingProfile = (patch: {
    interactionPolicy?: WallInteractionPolicy;
    arenaRect?: Rect2D;
    uiClickableZones?: UiClickableZone[];
    buttonTargets?: OstButtonTarget[];
  }): void => {
    if (!trainingProfile || !maps[0]) return;
    const next = updateTrainingProfile(trainingProfile.profileId, patch);
    if (!next) return;
    const clamped = withClampedProfile(next, maps[0]);
    setTrainingProfile(clamped);
    if (patch.interactionPolicy) setInteractionPolicy(clamped.interactionPolicy);
    if (patch.arenaRect) setArenaRect(clamped.arenaRect);
    if (patch.uiClickableZones) setUiClickableZones(clamped.uiClickableZones);
    if (patch.buttonTargets) setButtonTargets(clamped.buttonTargets);
  };

  const updateTargetCenter = (buttonId: string, x: number, y: number): void => {
    setButtonTargets((prev) => {
      const next = prev.map((b) =>
        b.id === buttonId ? { ...b, center: { x: Math.round(x), y: Math.round(y) } } : b
      );
      saveOstButtons(next);
      setButtonProfiles((profiles) => {
        const updated = profiles.map((p) =>
          p.name === activeButtonProfile ? { ...p, buttons: next } : p
        );
        saveOstButtonProfiles(updated);
        return updated;
      });
      persistTrainingProfile({ buttonTargets: next });
      return next;
    });
  };

  const selectProfile = (name: string): void => {
    const profile = buttonProfiles.find((p) => p.name === name);
    if (!profile) return;
    setActiveButtonProfile(name);
    saveActiveOstButtonProfileName(name);
    setButtonTargets(profile.buttons);
    saveOstButtons(profile.buttons);
    setQualificationCheck(null);
  };

  const saveProfile = (name: string): void => {
    const cleaned = name.trim();
    if (!cleaned) return;
    setButtonProfiles((prev) => {
      const exists = prev.some((p) => p.name === cleaned);
      const next = exists
        ? prev.map((p) => (p.name === cleaned ? { ...p, buttons: buttonTargets } : p))
        : [...prev, { name: cleaned, buttons: buttonTargets }];
      saveOstButtonProfiles(next);
      return next;
    });
    setActiveButtonProfile(cleaned);
    saveActiveOstButtonProfileName(cleaned);
    setProfileNameDraft('');
  };

  const deleteActiveProfile = (): void => {
    if (buttonProfiles.length <= 1) return;
    const nextProfiles = buttonProfiles.filter((p) => p.name !== activeButtonProfile);
    if (nextProfiles.length === 0) return;
    const fallback = nextProfiles[0];
    setButtonProfiles(nextProfiles);
    saveOstButtonProfiles(nextProfiles);
    setActiveButtonProfile(fallback.name);
    saveActiveOstButtonProfileName(fallback.name);
    setButtonTargets(fallback.buttons);
    saveOstButtons(fallback.buttons);
    setQualificationCheck(null);
  };

  const replayClickCapture = (evt: React.MouseEvent<SVGSVGElement>): void => {
    if (!mapForSelected) return;
    const svg = evt.currentTarget;
    const rect = svg.getBoundingClientRect();
    const relX = evt.clientX - rect.left;
    const relY = evt.clientY - rect.top;
    const useMapSpace = ostScaleMode || replayFullscreen;
    const displayW = useMapSpace ? mapForSelected.width : 960;
    const displayH = useMapSpace ? mapForSelected.height : 540;
    const x = (relX / Math.max(1, rect.width)) * displayW;
    const y = (relY / Math.max(1, rect.height)) * displayH;
    if (captureButtonId) {
      updateTargetCenter(captureButtonId, x, y);
      setCaptureButtonId(null);
      return;
    }
    if (editMode === 'none') return;
    if (!pendingRectStart) {
      setPendingRectStart({ x, y });
      return;
    }
    const nextRect = clampRect(
      {
        x: Math.min(pendingRectStart.x, x),
        y: Math.min(pendingRectStart.y, y),
        width: Math.abs(x - pendingRectStart.x),
        height: Math.abs(y - pendingRectStart.y),
      },
      mapForSelected
    );
    if (editMode === 'arena') {
      setArenaRect(nextRect);
      persistTrainingProfile({ arenaRect: nextRect });
    } else {
      const zone: UiClickableZone = {
        id: `zone-${Date.now()}`,
        label: `UI Zone ${uiClickableZones.length + 1}`,
        rect: nextRect,
      };
      const nextZones = [...uiClickableZones, zone];
      setUiClickableZones(nextZones);
      persistTrainingProfile({ uiClickableZones: nextZones });
    }
    setPendingRectStart(null);
    setEditMode('none');
  };

  const runQualificationCheck = (): void => {
    const probe = buildCalibrationProbeAgent(calibrationNoisePx);
    const out = evaluateQualification({
      agent: probe,
      buttons: buttonTargets,
      mode,
    });
    setQualificationCheck(out);
  };

  const applyMonitorTarget = async (): Promise<void> => {
    if (!window.desktopApi) return;
    setApplyingMonitorPreference(true);
    try {
      const out = await window.desktopApi.setMonitorPreference(monitorPreference);
      if (!out.ok) {
        alert(out.error || 'Could not set monitor preference.');
        return;
      }
      alert(
        `Monitor target saved as "${out.monitorPreference}". The window should move there now and keep using it next launch.`
      );
    } finally {
      setApplyingMonitorPreference(false);
    }
  };

  const dispatchControlsAction = (data: {
    source?: string;
    type?: string;
    value?: unknown;
  }): void => {
    if (!data || data.source !== 'wall-controls') return;
    switch (data.type) {
      case 'setMode':
        setMode((data.value as QualificationMode) ?? 'warmup');
        break;
      case 'setRounds':
        setRounds(Math.max(1, Number(data.value) || 1));
        break;
      case 'setPopulation':
        setPopulationSize(Math.max(4, Number(data.value) || 4));
        break;
      case 'setWinners':
        setWinnersPerRound(Math.max(1, Number(data.value) || 1));
        break;
      case 'setMonitorPref':
        if (
          data.value === 'primary' ||
          data.value === 'secondary' ||
          (typeof data.value === 'string' && /^id:\d+$/.test(data.value))
        ) {
          setMonitorPreference(data.value as `id:${number}` | 'primary' | 'secondary');
        }
        break;
      case 'setPolicy':
        if (
          data.value === 'buttons-only' ||
          data.value === 'annotated-ui' ||
          data.value === 'strict-no-ui'
        ) {
          const next = data.value as WallInteractionPolicy;
          setInteractionPolicy(next);
          persistTrainingProfile({ interactionPolicy: next });
        }
        break;
      case 'run':
        void runTournament();
        break;
      case 'loadMap':
        mapImageInputRef.current?.click();
        break;
      case 'loadMapDataUrl': {
        const payload = data.value as { dataUrl?: string; fileName?: string } | undefined;
        const dataUrl = String(payload?.dataUrl || '').trim();
        if (dataUrl) {
          void parseAndSetMapImage(dataUrl, payload?.fileName || 'controls-window-image');
        }
        break;
      }
      case 'leaderboard':
        openOrRefreshLeaderboard();
        break;
      case 'fullscreen':
        void toggleReplayFullscreen();
        break;
      case 'applyMonitor':
        void applyMonitorTarget();
        break;
      case 'winnersJson':
        if (result) {
          downloadText(
            `wall_battleship_winners_${Date.now()}.json`,
            JSON.stringify(result.winnersArtifact, null, 2),
            'application/json'
          );
        }
        break;
      case 'losersJson':
        if (result) {
          downloadText(
            `wall_battleship_losers_${Date.now()}.json`,
            JSON.stringify(result.losersArtifact, null, 2),
            'application/json'
          );
        }
        break;
      case 'reportMd':
        if (reportMd) {
          downloadText(`wall_battleship_report_${Date.now()}.md`, reportMd, 'text/markdown');
        }
        break;
      case 'startArenaEdit':
        setEditMode('arena');
        setPendingRectStart(null);
        break;
      case 'startZoneEdit':
        setEditMode('zone');
        setPendingRectStart(null);
        break;
      case 'clearZones':
        setUiClickableZones([]);
        persistTrainingProfile({ uiClickableZones: [] });
        break;
      case 'saveTemplate':
        if (trainingProfile) {
          saveTrainingTemplateForResolution({
            ...trainingProfile,
            interactionPolicy,
            arenaRect,
            uiClickableZones,
            buttonTargets,
          });
          alert(`Saved template for ${trainingProfile.resolutionKey}.`);
        }
        break;
      default:
        break;
    }
  };

  const openOrRefreshControlsWindow = (): void => {
    if (!useDetachedControls) return;
    const hadWindow = !!controlsWinRef.current && !controlsWinRef.current.closed;
    if (!hadWindow) {
      controlsWinRef.current = window.open(
        '',
        'wall-battleship-controls',
        'width=540,height=900,resizable=yes,scrollbars=yes'
      );
    }
    if (!controlsWinRef.current) return;
    try {
      (
        controlsWinRef.current as Window & {
          desktopApi?: Window['desktopApi'];
          __wallBattleshipControlBridge?: unknown;
        }
      ).desktopApi = window.desktopApi;
      (
        controlsWinRef.current as Window & {
          desktopApi?: Window['desktopApi'];
          __wallBattleshipControlBridge?: unknown;
        }
      ).__wallBattleshipControlBridge = (
        window as Window & { __wallBattleshipControlBridge?: unknown }
      ).__wallBattleshipControlBridge;
    } catch {
      // Ignore cross-context assignment issues; other channels may still work.
    }
    controlsWinRef.current.document.open();
    controlsWinRef.current.document.write(
      controlsWindowHtml({
        mode,
        rounds,
        populationSize,
        winnersPerRound,
        isRunning,
        ingestingImage,
        mapImageLabel,
        monitorPreference,
        displayOptions,
        result,
        interactionPolicy,
        arenaRect,
        uiZoneCount: uiClickableZones.length,
        profileId: trainingProfile?.profileId ?? '',
      })
    );
    controlsWinRef.current.document.close();
    if (!hadWindow) controlsWinRef.current.focus();
  };

  useEffect(() => {
    if (!useDetachedControls) return;
    openOrRefreshControlsWindow();
  }, [
    useDetachedControls,
    mode,
    rounds,
    populationSize,
    winnersPerRound,
    isRunning,
    ingestingImage,
    mapImageLabel,
    monitorPreference,
    displayOptions,
    result,
    interactionPolicy,
    arenaRect,
    uiClickableZones,
    trainingProfile,
  ]);

  useEffect(() => {
    const bridge = {
      setMode: (value: string) => setMode((value as QualificationMode) ?? 'warmup'),
      setRounds: (value: number) => setRounds(Math.max(1, Number(value) || 1)),
      setPopulation: (value: number) => setPopulationSize(Math.max(4, Number(value) || 4)),
      setWinners: (value: number) => setWinnersPerRound(Math.max(1, Number(value) || 1)),
      setPolicy: (value: string) => {
        if (value === 'buttons-only' || value === 'annotated-ui' || value === 'strict-no-ui') {
          setInteractionPolicy(value);
          persistTrainingProfile({ interactionPolicy: value });
        }
      },
      setMonitorPref: (value: string) => {
        if (
          value === 'primary' ||
          value === 'secondary' ||
          (typeof value === 'string' && /^id:\d+$/.test(value))
        ) {
          setMonitorPreference(value as `id:${number}` | 'primary' | 'secondary');
        }
      },
      run: () => {
        void runTournament();
      },
      loadMap: () => mapImageInputRef.current?.click(),
      loadMapDataUrl: (value: unknown) => {
        const payload = value as { dataUrl?: string; fileName?: string } | undefined;
        const dataUrl = String(payload?.dataUrl || '').trim();
        if (!dataUrl) return;
        void parseAndSetMapImage(dataUrl, payload?.fileName || 'controls-window-image');
      },
      leaderboard: () => openOrRefreshLeaderboard(),
      fullscreen: () => {
        void toggleReplayFullscreen();
      },
      applyMonitor: () => {
        void applyMonitorTarget();
      },
      winnersJson: () => {
        if (!result) return;
        downloadText(
          `wall_battleship_winners_${Date.now()}.json`,
          JSON.stringify(result.winnersArtifact, null, 2),
          'application/json'
        );
      },
      losersJson: () => {
        if (!result) return;
        downloadText(
          `wall_battleship_losers_${Date.now()}.json`,
          JSON.stringify(result.losersArtifact, null, 2),
          'application/json'
        );
      },
      reportMd: () => {
        if (!reportMd) return;
        downloadText(`wall_battleship_report_${Date.now()}.md`, reportMd, 'text/markdown');
      },
      startArenaEdit: () => {
        setEditMode('arena');
        setPendingRectStart(null);
      },
      startZoneEdit: () => {
        setEditMode('zone');
        setPendingRectStart(null);
      },
      clearZones: () => {
        setUiClickableZones([]);
        persistTrainingProfile({ uiClickableZones: [] });
      },
      saveTemplate: () => {
        if (!trainingProfile) return;
        saveTrainingTemplateForResolution({
          ...trainingProfile,
          interactionPolicy,
          arenaRect,
          uiClickableZones,
          buttonTargets,
        });
      },
    };
    (window as Window & { __wallBattleshipControlBridge?: typeof bridge }).__wallBattleshipControlBridge =
      bridge;
    return () => {
      delete (window as Window & { __wallBattleshipControlBridge?: typeof bridge })
        .__wallBattleshipControlBridge;
    };
  }, [
    result,
    reportMd,
    runTournament,
    applyMonitorTarget,
    trainingProfile,
    interactionPolicy,
    arenaRect,
    uiClickableZones,
    buttonTargets,
  ]);

  useEffect(() => {
    const onMessage = (evt: MessageEvent) => {
      const data = evt.data as
        | {
            source?: string;
            type?: string;
            value?: unknown;
          }
        | undefined;
      dispatchControlsAction(data ?? {});
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [dispatchControlsAction]);

  useEffect(() => {
    const desktopApi = window.desktopApi;
    if (!desktopApi?.onWallControl) return;
    const unsubscribe = desktopApi.onWallControl((payload) => {
      dispatchControlsAction(payload ?? {});
    });
    return () => unsubscribe?.();
  }, [dispatchControlsAction]);

  useEffect(() => {
    if (!window.BroadcastChannel) return;
    const bc = new BroadcastChannel('wall-battleship-controls');
    bc.onmessage = (evt) => {
      const payload = evt.data as { source?: string; type?: string; value?: unknown } | undefined;
      dispatchControlsAction(payload ?? {});
    };
    return () => bc.close();
  }, [dispatchControlsAction]);

  useEffect(() => {
    const key = 'wall-battleship-control-command-v1';
    const onStorage = (evt: StorageEvent) => {
      if (evt.key !== key || !evt.newValue) return;
      try {
        const payload = JSON.parse(evt.newValue) as {
          source?: string;
          type?: string;
          value?: unknown;
        };
        dispatchControlsAction(payload ?? {});
      } catch {
        // Ignore malformed payloads.
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [dispatchControlsAction]);

  const openOrRefreshLeaderboard = (): void => {
    if (!result) return;
    if (!leaderboardWinRef.current || leaderboardWinRef.current.closed) {
      leaderboardWinRef.current = window.open(
        '',
        'wall-battleship-leaderboard',
        'width=760,height=840,resizable=yes,scrollbars=yes'
      );
    }
    if (!leaderboardWinRef.current) return;
    leaderboardWinRef.current.document.open();
    leaderboardWinRef.current.document.write(leaderboardHtml(result));
    leaderboardWinRef.current.document.close();
    leaderboardWinRef.current.focus();
  };

  useEffect(() => {
    if (!result) return;
    if (!leaderboardWinRef.current || leaderboardWinRef.current.closed) return;
    openOrRefreshLeaderboard();
  }, [result]);

  const toggleReplayFullscreen = async (): Promise<void> => {
    if (!fullscreenContainerRef.current) return;
    if (!document.fullscreenElement) {
      await fullscreenContainerRef.current.requestFullscreen();
      return;
    }
    await document.exitFullscreen();
  };

  return (
    <div className="space-y-4">
      <div
        ref={fullscreenContainerRef}
        className="relative rounded-xl border border-slate-800 bg-slate-900/40 p-3"
        style={replayFullscreen ? { width: '100vw', height: '100vh', padding: '8px' } : undefined}
      >
        {!useDetachedControls && (
          <div
            className="absolute z-20 rounded-xl border border-slate-700 bg-slate-950/95 p-3 shadow-2xl"
            style={{ top: `${overlayTop}px`, left: `${overlayLeft}px`, width: `${overlayWidth}px` }}
          >
          <div className="mb-2 text-sm font-semibold">Wall Battleship Controls</div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <label>
              Mode
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as QualificationMode)}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1"
              >
                <option value="warmup">warmup</option>
                <option value="ranked">ranked</option>
              </select>
            </label>
            <label>
              Rounds
              <input
                type="number"
                min={1}
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1"
              />
            </label>
            <label>
              Population
              <input
                type="number"
                min={4}
                value={populationSize}
                onChange={(e) => setPopulationSize(Number(e.target.value))}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1"
              />
            </label>
            <label>
              Winners
              <input
                type="number"
                min={1}
                value={winnersPerRound}
                onChange={(e) => setWinnersPerRound(Number(e.target.value))}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1"
              />
            </label>
            <label className="col-span-2">
              Interaction policy
              <select
                value={interactionPolicy}
                onChange={(e) => {
                  const next = e.target.value as WallInteractionPolicy;
                  setInteractionPolicy(next);
                  persistTrainingProfile({ interactionPolicy: next });
                }}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1"
              >
                <option value="buttons-only">buttons-only</option>
                <option value="annotated-ui">annotated-ui</option>
                <option value="strict-no-ui">strict-no-ui</option>
              </select>
            </label>
            <label>
              Panel top
              <input
                type="number"
                value={overlayTop}
                onChange={(e) => setOverlayTop(Number(e.target.value))}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1"
              />
            </label>
            <label>
              Panel left
              <input
                type="number"
                value={overlayLeft}
                onChange={(e) => setOverlayLeft(Number(e.target.value))}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1"
              />
            </label>
            <label>
              Panel width
              <input
                type="number"
                min={280}
                value={overlayWidth}
                onChange={(e) => setOverlayWidth(Number(e.target.value))}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1"
              />
            </label>
            {window.desktopApi && (
              <label className="col-span-2">
                Target monitor
                <div className="mt-1 flex gap-2">
                  <select
                    value={monitorPreference}
                    onChange={(e) =>
                      setMonitorPreference(
                        e.target.value as `id:${number}` | 'primary' | 'secondary'
                      )
                    }
                    className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1"
                  >
                    {displayOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => void applyMonitorTarget()}
                    disabled={applyingMonitorPreference}
                    className="rounded border border-blue-700/50 px-2 py-1 text-xs hover:bg-blue-900/20 disabled:opacity-40"
                  >
                    {applyingMonitorPreference ? 'Applying…' : 'Apply'}
                  </button>
                </div>
              </label>
            )}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={ingestingImage}
              onClick={() => mapImageInputRef.current?.click()}
              className="rounded border border-blue-700/50 px-2 py-1 text-xs hover:bg-blue-900/20 disabled:opacity-40"
            >
              {ingestingImage ? 'Parsing…' : 'Load wall image'}
            </button>
            <input
              ref={mapImageInputRef}
              type="file"
              accept="image/png,image/jpeg,image/jpg,image/webp,image/gif,image/bmp"
              className="hidden"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                try {
                  const src = await readDataUrlFile(file);
                  await parseAndSetMapImage(src, file.name);
                } finally {
                  e.currentTarget.value = '';
                }
              }}
            />
            <button
              type="button"
              onClick={runTournament}
              disabled={isRunning}
              className="rounded bg-indigo-700 px-2 py-1 text-xs font-semibold hover:bg-indigo-600 disabled:opacity-50"
            >
              {isRunning ? 'Running…' : 'Run'}
            </button>
            <button
              type="button"
              disabled={!result}
              onClick={openOrRefreshLeaderboard}
              className="rounded border border-emerald-700/50 px-2 py-1 text-xs hover:bg-emerald-900/20 disabled:opacity-40"
            >
              Leaderboard window
            </button>
            <button
              type="button"
              disabled={!result}
              onClick={() =>
                result &&
                downloadText(
                  `wall_battleship_winners_${Date.now()}.json`,
                  JSON.stringify(result.winnersArtifact, null, 2),
                  'application/json'
                )
              }
              className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800 disabled:opacity-40"
            >
              Winners JSON
            </button>
            <label className="flex items-center gap-2 rounded border border-slate-700 px-2 py-1 text-xs">
              <input
                type="checkbox"
                checked={ostScaleMode}
                onChange={(e) => setOstScaleMode(e.target.checked)}
              />
              OST 1:1
            </label>
            <button
              type="button"
              onClick={() => setShowCalibration((v) => !v)}
              className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
            >
              {showCalibration ? 'Hide button centers' : 'Calibrate button centers'}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditMode('arena');
                setPendingRectStart(null);
              }}
              className="rounded border border-amber-700/50 px-2 py-1 text-xs hover:bg-amber-900/20"
            >
              Draw arena
            </button>
            <button
              type="button"
              onClick={() => {
                setEditMode('zone');
                setPendingRectStart(null);
              }}
              className="rounded border border-cyan-700/50 px-2 py-1 text-xs hover:bg-cyan-900/20"
            >
              Add UI zone
            </button>
            <button
              type="button"
              onClick={() => {
                setUiClickableZones([]);
                persistTrainingProfile({ uiClickableZones: [] });
              }}
              className="rounded border border-rose-700/50 px-2 py-1 text-xs hover:bg-rose-900/20"
            >
              Clear zones
            </button>
            <button
              type="button"
              disabled={!trainingProfile}
              onClick={() =>
                trainingProfile &&
                saveTrainingTemplateForResolution({
                  ...trainingProfile,
                  interactionPolicy,
                  arenaRect,
                  uiClickableZones,
                  buttonTargets,
                })
              }
              className="rounded border border-indigo-700/50 px-2 py-1 text-xs hover:bg-indigo-900/20 disabled:opacity-40"
            >
              Save template
            </button>
          </div>
          <div className="mt-2 text-[11px] text-slate-400">
            Warm-up gate: 7/10 center clicks, ranked gate: 10/10. Map image: {mapImageLabel}.
            Policy: {interactionPolicy}. Arena edit: {editMode !== 'none' ? `${editMode} (click 2 points)` : 'off'}.
          </div>
          {showCalibration && (
            <div className="mt-2 rounded border border-slate-700 p-2 text-[11px]">
              <div className="mb-1 font-semibold">Center-point calibration</div>
              <div className="mb-1 text-slate-400">
                Pick a button, then click its true center on the replay image.
              </div>
              <div className="mb-2 grid grid-cols-2 gap-2">
                <label>
                  Profile
                  <select
                    value={activeButtonProfile}
                    onChange={(e) => selectProfile(e.target.value)}
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs"
                  >
                    {buttonProfiles.map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  New profile name
                  <input
                    type="text"
                    value={profileNameDraft}
                    onChange={(e) => setProfileNameDraft(e.target.value)}
                    placeholder="e.g. Office-1080p"
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs"
                  />
                </label>
              </div>
              <div className="mb-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => saveProfile(activeButtonProfile)}
                  className="rounded border border-blue-700/50 px-2 py-1 text-xs hover:bg-blue-900/20"
                >
                  Save to current
                </button>
                <button
                  type="button"
                  onClick={() => saveProfile(profileNameDraft)}
                  className="rounded border border-indigo-700/50 px-2 py-1 text-xs hover:bg-indigo-900/20"
                >
                  Save as new
                </button>
                <button
                  type="button"
                  disabled={buttonProfiles.length <= 1}
                  onClick={deleteActiveProfile}
                  className="rounded border border-rose-700/50 px-2 py-1 text-xs hover:bg-rose-900/20 disabled:opacity-40"
                >
                  Delete profile
                </button>
              </div>
              <div className="max-h-40 space-y-1 overflow-y-auto">
                {buttonTargets.map((b) => (
                  <div key={b.id} className="flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => setCaptureButtonId(b.id)}
                      className={`rounded px-2 py-1 text-left ${captureButtonId === b.id ? 'bg-indigo-700 text-white' : 'border border-slate-700 hover:bg-slate-800'}`}
                    >
                      {b.label}
                    </button>
                    <span className="text-slate-300">
                      ({Math.round(b.center.x)}, {Math.round(b.center.y)})
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  onClick={runQualificationCheck}
                  className="rounded border border-emerald-700/50 px-2 py-1 text-xs hover:bg-emerald-900/20"
                >
                  Qualification check
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const next = resetOstButtons();
                    setButtonTargets(next);
                    setButtonProfiles((prev) => {
                      const updated = prev.map((p) =>
                        p.name === activeButtonProfile ? { ...p, buttons: next } : p
                      );
                      saveOstButtonProfiles(updated);
                      return updated;
                    });
                    setQualificationCheck(null);
                  }}
                  className="rounded border border-rose-700/50 px-2 py-1 text-xs hover:bg-rose-900/20"
                >
                  Reset defaults
                </button>
                <button
                  type="button"
                  onClick={() => setCaptureButtonId(null)}
                  className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
                >
                  Cancel capture
                </button>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <label>
                  Sim noise px
                  <input
                    type="number"
                    min={0}
                    step={0.25}
                    value={calibrationNoisePx}
                    onChange={(e) => setCalibrationNoisePx(Number(e.target.value))}
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs"
                  />
                </label>
                {qualificationCheck && (
                  <div className="rounded border border-slate-700 px-2 py-1">
                    <div className="font-semibold">
                      {qualificationCheck.pass ? 'PASS' : 'FAIL'} ({qualificationCheck.totalHits}/10)
                    </div>
                    <div className="text-slate-400">
                      Need {qualificationCheck.minHitsRequired}, mean {qualificationCheck.meanOffsetPx.toFixed(2)}px
                    </div>
                  </div>
                )}
              </div>
              {qualificationCheck && (
                <div className="mt-2 max-h-48 overflow-y-auto rounded border border-slate-700">
                  {qualificationCheck.attempts.map((a) => (
                    <div
                      key={`q-${a.buttonId}`}
                      className="flex items-center justify-between border-b border-slate-800 px-2 py-1 last:border-b-0"
                    >
                      <span>{buttonTargets.find((b) => b.id === a.buttonId)?.label ?? a.buttonId}</span>
                      <span className={a.hit ? 'text-emerald-300' : 'text-rose-300'}>
                        {a.hit ? 'hit' : 'miss'} ({a.offsetPx.toFixed(2)}px)
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          </div>
        )}

        <div style={{ height: replayFullscreen ? '100%' : undefined }}>
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm font-semibold">Live Segment Replay</div>
            <div className="flex items-center gap-2">
              {useDetachedControls && (
                <button
                  type="button"
                  onClick={openOrRefreshControlsWindow}
                  className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
                >
                  Controls window
                </button>
              )}
              <button
                type="button"
                onClick={() => void toggleReplayFullscreen()}
                className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
              >
                {replayFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
              </button>
            </div>
          </div>
          {selectedEpisode && mapForSelected ? (
            <>
              {!replayFullscreen && (
                <>
                  <div className="mb-2 flex items-center gap-2">
                    <select
                      value={selectedEpisodeKey}
                      onChange={(e) => {
                        setSelectedEpisodeKey(e.target.value);
                        setStep(1);
                      }}
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
                    >
                      {result?.rounds.flatMap((round) =>
                        round.episodes.map((ep) => (
                          <option
                            key={`${round.round}|${ep.agentId}|${ep.mapId}`}
                            value={`${ep.agentId}|${ep.mapId}|${round.round}`}
                          >
                            R{round.round} - {ep.agentId} - {ep.mapId} - score {ep.score.toFixed(1)}
                          </option>
                        ))
                      )}
                    </select>
                  </div>
                  <input
                    type="range"
                    min={1}
                    max={selectedEpisode.trace.length}
                    value={Math.max(1, Math.min(step, selectedEpisode.trace.length))}
                    onChange={(e) => setStep(Number(e.target.value))}
                    className="mb-2 w-full"
                  />
                  <div className="mb-2 text-xs text-slate-400">
                    Step {Math.max(1, Math.min(step, selectedEpisode.trace.length))}/
                    {selectedEpisode.trace.length}
                  </div>
                </>
              )}
              <div
                ref={replaySurfaceRef}
                className={
                  replayFullscreen
                    ? 'h-full overflow-hidden rounded border border-slate-700 bg-slate-950 p-0'
                    : 'overflow-auto rounded border border-slate-700 bg-slate-950 p-1'
                }
                style={
                  replayFullscreen
                    ? {
                        height: 'calc(100vh - 52px)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }
                    : undefined
                }
              >
                {(() => {
                  const useMapSpace = ostScaleMode || replayFullscreen;
                  const displayW = useMapSpace ? mapForSelected.width : 960;
                  const displayH = useMapSpace ? mapForSelected.height : 540;
                  const toDisplay = (p: { x: number; y: number }) =>
                    useMapSpace
                      ? p
                      : toScreen(mapForSelected, p.x, p.y, displayW, displayH);
                  const stroke = ostScaleMode ? 3 : 2;
                  return (
                    <svg
                      viewBox={`0 0 ${displayW} ${displayH}`}
                      className={ostScaleMode || replayFullscreen ? '' : 'w-full'}
                      onClick={replayClickCapture}
                      preserveAspectRatio="xMidYMid meet"
                      style={
                        replayFullscreen
                          ? {
                              width: '100%',
                              height: '100%',
                              maxWidth: '100%',
                              maxHeight: '100%',
                              cursor: captureButtonId ? 'crosshair' : 'default',
                            }
                          : ostScaleMode
                          ? {
                              width: `${displayW}px`,
                              height: `${displayH}px`,
                              maxWidth: 'none',
                              cursor: captureButtonId ? 'crosshair' : 'default',
                            }
                          : { cursor: captureButtonId ? 'crosshair' : 'default' }
                      }
                    >
                      {mapForSelected.backgroundUrl && (
                        <image
                          href={mapForSelected.backgroundUrl}
                          x={0}
                          y={0}
                          width={displayW}
                          height={displayH}
                          preserveAspectRatio="xMidYMid meet"
                        />
                      )}
                      {(() => {
                        const ar = toDisplay({ x: arenaRect.x, y: arenaRect.y });
                        const br = toDisplay({
                          x: arenaRect.x + arenaRect.width,
                          y: arenaRect.y + arenaRect.height,
                        });
                        return (
                          <rect
                            x={Math.min(ar.x, br.x)}
                            y={Math.min(ar.y, br.y)}
                            width={Math.abs(br.x - ar.x)}
                            height={Math.abs(br.y - ar.y)}
                            fill="none"
                            stroke="#f59e0b"
                            strokeDasharray="6 4"
                            strokeWidth={2}
                          />
                        );
                      })()}
                      {uiClickableZones.map((zone) => {
                        const a = toDisplay({ x: zone.rect.x, y: zone.rect.y });
                        const b = toDisplay({
                          x: zone.rect.x + zone.rect.width,
                          y: zone.rect.y + zone.rect.height,
                        });
                        return (
                          <g key={zone.id}>
                            <rect
                              x={Math.min(a.x, b.x)}
                              y={Math.min(a.y, b.y)}
                              width={Math.abs(b.x - a.x)}
                              height={Math.abs(b.y - a.y)}
                              fill="none"
                              stroke="#22d3ee"
                              strokeDasharray="4 3"
                              strokeWidth={1.6}
                            />
                            <text x={Math.min(a.x, b.x) + 4} y={Math.min(a.y, b.y) + 12} fill="#67e8f9" fontSize={10}>
                              {zone.label}
                            </text>
                          </g>
                        );
                      })}
                      {mapForSelected.walls.map((wall) => (
                        <polyline
                          key={wall.wallId}
                          points={wall.polyline
                            .map((p) => {
                              const pp = toDisplay(p);
                              return `${pp.x},${pp.y}`;
                            })
                            .join(' ')}
                          fill="none"
                          stroke="#4f46e5"
                          strokeWidth={stroke}
                        />
                      ))}
                      {selectedEpisode.trace
                        .slice(0, Math.max(1, Math.min(step, selectedEpisode.trace.length)))
                        .map((row, idx) => {
                          const a = toDisplay(row.segment.a);
                          const b = toDisplay(row.segment.b);
                          return (
                            <line
                              key={`${idx}-${row.turn}`}
                              x1={a.x}
                              y1={a.y}
                              x2={b.x}
                              y2={b.y}
                              stroke={row.validHit ? '#22c55e' : '#ef4444'}
                              strokeWidth={2.5}
                              strokeLinecap="round"
                            />
                          );
                        })}
                      {showCalibration &&
                        buttonTargets.map((b) => {
                          const p = toDisplay(b.center);
                          return (
                            <g key={`btn-${b.id}`}>
                              <circle cx={p.x} cy={p.y} r={4} fill="#eab308" />
                              <text x={p.x + 6} y={p.y - 6} fill="#fde68a" fontSize={10}>
                                {b.label}
                              </text>
                            </g>
                          );
                        })}
                    </svg>
                  );
                })()}
              </div>
            </>
          ) : (
            <div className="text-xs text-slate-400">
              Run tournament to start live segment replay.
            </div>
          )}
        </div>
      </div>

      {/* Lightweight fallback tools */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-2">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!reportMd}
            onClick={() =>
              downloadText(
                `wall_battleship_report_${Date.now()}.md`,
                reportMd,
                'text/markdown'
              )
            }
            className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800 disabled:opacity-40"
          >
            Report MD
          </button>
          <button
            type="button"
            disabled={!result}
            onClick={() =>
              result &&
              downloadText(
                `wall_battleship_losers_${Date.now()}.json`,
                JSON.stringify(result.losersArtifact, null, 2),
                'application/json'
              )
            }
            className="rounded border border-rose-700/50 px-2 py-1 text-xs hover:bg-rose-900/20 disabled:opacity-40"
          >
            Losers JSON
          </button>
          <label className="text-xs">
            Load map JSON
            <input
              type="file"
              accept="application/json"
              className="ml-2 text-xs"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                try {
                  const parsed = await readJsonFile<WallHuntMap[] | WallHuntMap>(f);
                  const next = Array.isArray(parsed) ? parsed : [parsed];
                  if (next.length > 0) setMaps(next);
                } catch (err) {
                  alert(`Invalid map JSON: ${String(err)}`);
                }
              }}
            />
          </label>
        </div>
      </div>
    </div>
  );
}

