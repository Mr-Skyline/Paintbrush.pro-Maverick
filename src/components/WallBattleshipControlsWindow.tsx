import { useMemo, useState, useEffect } from 'react';

type ActionStatus = 'sent' | 'received' | 'executed' | 'failed';

type ControlState = {
  mode: 'warmup' | 'ranked';
  rounds: number;
  populationSize: number;
  winnersPerRound: number;
  isRunning: boolean;
  ingestingImage: boolean;
  mapImageLabel: string;
  monitorPreference: string;
  displayOptions: Array<{ value: string; label: string }>;
  interactionPolicy: 'buttons-only' | 'annotated-ui' | 'strict-no-ui';
  arenaRect: { x: number; y: number; width: number; height: number };
  uiZoneCount: number;
  profileId: string;
  finalWinners: string[];
  latestRound: {
    round: number;
    winners: string[];
    leaderboard: Array<{
      agentId: string;
      score: number;
      completedWalls: number;
      segmentsTotal: number;
      invalidActions: number;
      qualificationPass: boolean;
    }>;
  } | null;
};

const DEFAULT_STATE: ControlState = {
  mode: 'warmup',
  rounds: 5,
  populationSize: 12,
  winnersPerRound: 4,
  isRunning: false,
  ingestingImage: false,
  mapImageLabel: 'none',
  monitorPreference: 'secondary',
  displayOptions: [
    { value: 'primary', label: 'Primary monitor' },
    { value: 'secondary', label: 'Secondary monitor' },
  ],
  interactionPolicy: 'buttons-only',
  arenaRect: { x: 100, y: 100, width: 400, height: 400 },
  uiZoneCount: 0,
  profileId: '',
  finalWinners: [],
  latestRound: null,
};

function mkActionId(type: string): string {
  return `${type}-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
}

export function WallBattleshipControlsWindow() {
  const [snapshot, setSnapshot] = useState<ControlState>(DEFAULT_STATE);
  const [acks, setAcks] = useState<Record<string, { status: ActionStatus; message?: string }>>({});
  const [lastActionId, setLastActionId] = useState('');

  useEffect(() => {
    const offState = window.desktopApi?.onWallState?.((payload) => {
      if (!payload || typeof payload !== 'object') return;
      setSnapshot((prev) => ({ ...prev, ...(payload as Partial<ControlState>) }));
    });
    const offStatus = window.desktopApi?.onWallStatus?.((payload) => {
      if (!payload || typeof payload !== 'object') return;
      const p = payload as {
        actionId?: string;
        status?: 'received' | 'executed' | 'failed';
        message?: string;
      };
      if (!p.actionId || !p.status) return;
      setAcks((prev) => ({
        ...prev,
        [p.actionId!]: { status: p.status!, message: p.message },
      }));
    });
    return () => {
      offState?.();
      offStatus?.();
    };
  }, []);

  const latestAck = useMemo(() => {
    if (!lastActionId) return null;
    return acks[lastActionId] ?? null;
  }, [acks, lastActionId]);

  const send = async (type: string, value?: unknown): Promise<void> => {
    const actionId = mkActionId(type);
    setLastActionId(actionId);
    setAcks((prev) => ({ ...prev, [actionId]: { status: 'sent' } }));
    const out = await window.desktopApi?.sendWallControl({
      source: 'wall-controls',
      type,
      value,
      actionId,
    });
    if (!out?.ok) {
      setAcks((prev) => ({
        ...prev,
        [actionId]: { status: 'failed', message: out?.error || 'Send failed.' },
      }));
    }
  };

  const onFileSelected = async (file?: File): Promise<void> => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      await send('loadMapDataUrl', { dataUrl: String(reader.result || ''), fileName: file.name });
    };
    reader.readAsDataURL(file);
  };

  return (
    <div className="min-h-screen bg-slate-950 p-3 text-slate-100">
      <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
        <div className="mb-2 text-sm font-semibold">Wall Battleship Controls</div>
        <div className="mb-2 text-[11px] text-slate-400">
          ACK: {latestAck ? `${latestAck.status}${latestAck.message ? ` - ${latestAck.message}` : ''}` : 'idle'}
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <label>
            Mode
            <select
              value={snapshot.mode}
              onChange={(e) => void send('setMode', e.target.value)}
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
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
              value={snapshot.rounds}
              onChange={(e) => void send('setRounds', Number(e.target.value))}
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
            />
          </label>
          <label>
            Population
            <input
              type="number"
              min={4}
              value={snapshot.populationSize}
              onChange={(e) => void send('setPopulation', Number(e.target.value))}
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
            />
          </label>
          <label>
            Winners
            <input
              type="number"
              min={1}
              value={snapshot.winnersPerRound}
              onChange={(e) => void send('setWinners', Number(e.target.value))}
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
            />
          </label>
          <label className="col-span-2">
            Interaction policy
            <select
              value={snapshot.interactionPolicy}
              onChange={(e) => void send('setPolicy', e.target.value)}
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
            >
              <option value="buttons-only">buttons-only</option>
              <option value="annotated-ui">annotated-ui</option>
              <option value="strict-no-ui">strict-no-ui</option>
            </select>
          </label>
          <label className="col-span-2">
            Target monitor
            <div className="mt-1 flex gap-2">
              <select
                value={snapshot.monitorPreference}
                onChange={(e) => void send('setMonitorPref', e.target.value)}
                className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
              >
                {snapshot.displayOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void send('applyMonitor')}
                className="rounded border border-blue-700/50 px-2 py-1 hover:bg-blue-900/20"
              >
                Apply
              </button>
            </div>
          </label>
        </div>
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          <button
            type="button"
            onClick={() => void send('run')}
            disabled={snapshot.isRunning}
            className="rounded bg-indigo-700 px-2 py-1 font-semibold hover:bg-indigo-600 disabled:opacity-40"
          >
            {snapshot.isRunning ? 'Running...' : 'Run tournament'}
          </button>
          <button
            type="button"
            onClick={() => void send('leaderboard')}
            className="rounded border border-emerald-700/50 px-2 py-1 hover:bg-emerald-900/20"
          >
            Leaderboard window
          </button>
          <button
            type="button"
            onClick={() => void send('fullscreen')}
            className="rounded border border-slate-700 px-2 py-1 hover:bg-slate-800"
          >
            Toggle fullscreen
          </button>
          <button type="button" onClick={() => void send('winnersJson')} className="rounded border border-slate-700 px-2 py-1 hover:bg-slate-800">
            Winners JSON
          </button>
          <button type="button" onClick={() => void send('losersJson')} className="rounded border border-slate-700 px-2 py-1 hover:bg-slate-800">
            Losers JSON
          </button>
          <button type="button" onClick={() => void send('reportMd')} className="rounded border border-slate-700 px-2 py-1 hover:bg-slate-800">
            Report MD
          </button>
        </div>
        <div className="mt-2 rounded border border-slate-800 bg-slate-950/70 p-2 text-xs">
          <div className="mb-1">Wall map image upload</div>
          <input
            type="file"
            accept="image/png,image/jpeg,image/jpg,image/webp,image/gif,image/bmp"
            onChange={(e) => void onFileSelected(e.target.files?.[0])}
          />
          <div className="mt-1 text-[11px] text-slate-400">
            Map: {snapshot.mapImageLabel} | Profile: {snapshot.profileId || 'none'}
          </div>
          <div className="text-[11px] text-slate-400">
            Arena: x={Math.round(snapshot.arenaRect.x)}, y={Math.round(snapshot.arenaRect.y)}, w=
            {Math.round(snapshot.arenaRect.width)}, h={Math.round(snapshot.arenaRect.height)} | zones: {snapshot.uiZoneCount}
          </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          <button type="button" onClick={() => void send('startArenaEdit')} className="rounded border border-amber-700/50 px-2 py-1 hover:bg-amber-900/20">
            Draw arena
          </button>
          <button type="button" onClick={() => void send('startZoneEdit')} className="rounded border border-cyan-700/50 px-2 py-1 hover:bg-cyan-900/20">
            Add UI zone
          </button>
          <button type="button" onClick={() => void send('clearZones')} className="rounded border border-rose-700/50 px-2 py-1 hover:bg-rose-900/20">
            Clear zones
          </button>
          <button type="button" onClick={() => void send('saveTemplate')} className="rounded border border-indigo-700/50 px-2 py-1 hover:bg-indigo-900/20">
            Save template
          </button>
        </div>
      </div>

      <div className="mt-3 rounded-xl border border-slate-800 bg-slate-900/70 p-3">
        <div className="text-sm font-semibold">Tournament results</div>
        <div className="mt-1 text-xs text-slate-400">
          Final winners: {snapshot.finalWinners.join(', ') || 'none yet'}
        </div>
        {!snapshot.latestRound ? (
          <div className="mt-1 text-xs text-slate-400">No rounds yet.</div>
        ) : (
          <>
            <div className="mt-1 text-xs text-slate-400">
              Round {snapshot.latestRound.round} winners: {snapshot.latestRound.winners.join(', ') || 'none'}
            </div>
            <div className="mt-2 max-h-64 overflow-y-auto rounded border border-slate-800">
              <table className="w-full border-collapse text-xs">
                <thead className="bg-slate-800/70">
                  <tr>
                    <th className="border border-slate-700 px-2 py-1 text-left">Agent</th>
                    <th className="border border-slate-700 px-2 py-1 text-left">Score</th>
                    <th className="border border-slate-700 px-2 py-1 text-left">Walls</th>
                    <th className="border border-slate-700 px-2 py-1 text-left">Segs</th>
                    <th className="border border-slate-700 px-2 py-1 text-left">Invalid</th>
                    <th className="border border-slate-700 px-2 py-1 text-left">Q</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.latestRound.leaderboard.slice(0, 12).map((row) => (
                    <tr key={row.agentId}>
                      <td className="border border-slate-700 px-2 py-1">{row.agentId}</td>
                      <td className="border border-slate-700 px-2 py-1">{row.score.toFixed(1)}</td>
                      <td className="border border-slate-700 px-2 py-1">{row.completedWalls}</td>
                      <td className="border border-slate-700 px-2 py-1">{row.segmentsTotal}</td>
                      <td className="border border-slate-700 px-2 py-1">{row.invalidActions ?? 0}</td>
                      <td className="border border-slate-700 px-2 py-1">{row.qualificationPass ? 'pass' : 'fail'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
