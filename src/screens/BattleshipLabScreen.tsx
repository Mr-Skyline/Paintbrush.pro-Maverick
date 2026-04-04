import { useEffect, useMemo, useState } from 'react';
import {
  applyShot,
  buildPolicyContext,
  createGame,
} from '@/battleship/engine';
import type {
  BattleshipGameState,
  BattleshipPolicy,
  CellState,
  Coord,
  PolicyDecision,
  ShotResult,
} from '@/battleship/types';
import { createHuntTargetPolicy } from '@/battleship/policies/huntTargetPolicy';
import { RlHybridPolicy } from '@/battleship/policies/rlHybridPolicy';
import { trainHybridPolicy, type TrainingReport } from '@/battleship/training';
import { useNavigationStore } from '@/store/navigationStore';
import { WallBattleshipLab } from '@/components/WallBattleshipLab';

const cellClass = (state: CellState, isClickable: boolean): string => {
  const base =
    'h-8 w-8 rounded border border-slate-700 text-[10px] font-semibold';
  if (state === 'miss') return `${base} bg-slate-700 text-slate-200`;
  if (state === 'hit') return `${base} bg-orange-600 text-white`;
  if (state === 'sunk') return `${base} bg-rose-700 text-white`;
  return `${base} ${isClickable ? 'bg-slate-900 hover:bg-slate-800' : 'bg-slate-900'}`;
};

const coordLabel = (coord: Coord): string =>
  `${String.fromCharCode(65 + coord.x)}${coord.y + 1}`;

const downloadText = (filename: string, content: string, mime = 'text/plain'): void => {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
};

const reportMarkdown = (report: TrainingReport): string => {
  const lines: string[] = [];
  lines.push(`# Battleship Benchmark Report`);
  lines.push('');
  lines.push(`- generated_at: ${report.generatedAt}`);
  lines.push(`- train_episodes: ${report.trainEpisodes}`);
  lines.push(`- benchmark_episodes: ${report.benchmarkEpisodes}`);
  lines.push('');
  lines.push(`| policy | completion | avg_shots | p50 | p90 | avg_sink_turn |`);
  lines.push(`|---|---:|---:|---:|---:|---:|`);
  for (const row of report.metrics) {
    lines.push(
      `| ${row.policyId} | ${(row.completionRate * 100).toFixed(1)}% | ${row.avgShots.toFixed(2)} | ${row.p50Shots.toFixed(2)} | ${row.p90Shots.toFixed(2)} | ${row.avgSinkTurn.toFixed(2)} |`
    );
  }
  return lines.join('\n');
};

const firstUnknownCell = (game: BattleshipGameState): Coord | null => {
  for (let y = 0; y < game.publicBoard.size; y += 1) {
    for (let x = 0; x < game.publicBoard.size; x += 1) {
      if (game.publicBoard.cells[y][x] === 'unknown') return { x, y };
    }
  }
  return null;
};

interface MatchState {
  aiFleet: BattleshipGameState;
  humanFleet: BattleshipGameState;
  humanTurn: boolean;
  winner: 'human' | 'ai' | null;
  aiLastResult: ShotResult | null;
  humanAiLastResult: ShotResult | null;
  aiDecisionLog: Array<{
    actor: 'ai' | 'human-ai';
    turn: number;
    shot: Coord;
    confidence: number;
    reason: string;
    result: ShotResult['kind'];
    top: PolicyDecision['rankedCandidates'];
  }>;
}

const buildMatch = (): MatchState => ({
  aiFleet: createGame({ seed: Date.now() }),
  humanFleet: createGame({ seed: Date.now() + 7777 }),
  humanTurn: true,
  winner: null,
  aiLastResult: null,
  humanAiLastResult: null,
  aiDecisionLog: [],
});

export function BattleshipLabScreen() {
  const goToProjects = useNavigationStore((s) => s.goToProjects);
  const [match, setMatch] = useState<MatchState>(() => buildMatch());
  const [report, setReport] = useState<TrainingReport | null>(null);
  const [isTraining, setIsTraining] = useState(false);
  const [trainEpisodes, setTrainEpisodes] = useState(1200);
  const [benchmarkEpisodes, setBenchmarkEpisodes] = useState(250);
  const [hybrid] = useState(() => new RlHybridPolicy({ seed: 9001 }));
  const [hybridMirror] = useState(() => new RlHybridPolicy({ seed: 13337 }));
  const [useHybrid, setUseHybrid] = useState(true);
  const [aiVsAiMode, setAiVsAiMode] = useState(false);
  const [isAutoPlaying, setIsAutoPlaying] = useState(false);
  const [autoPlayDelayMs, setAutoPlayDelayMs] = useState(360);
  const [labMode, setLabMode] = useState<'classic' | 'wall'>('classic');

  const activePolicy = useMemo(
    () => (useHybrid ? hybrid : createHuntTargetPolicy()),
    [hybrid, useHybrid]
  );
  const mirrorPolicy = useMemo(
    () => (useHybrid ? hybridMirror : createHuntTargetPolicy()),
    [hybridMirror, useHybrid]
  );

  const resetMatch = (): void => {
    setIsAutoPlaying(false);
    setMatch(buildMatch());
  };

  const runPolicyTurn = (
    fleet: BattleshipGameState,
    lastResult: ShotResult | null,
    policy: BattleshipPolicy,
    actor: 'ai' | 'human-ai'
  ): {
    result: ShotResult;
    decision: PolicyDecision;
  } => {
    const prev = buildPolicyContext(fleet, lastResult);
    let decision = policy.decide(prev);
    let result = applyShot(fleet, decision.shot);

    // Safety: never allow autoplay to stall on repeated shots.
    if (result.kind === 'repeat') {
      const fallback = firstUnknownCell(fleet);
      if (fallback) {
        decision = {
          shot: fallback,
          confidence: 0.35,
          reason: `${actor}_repeat_guard_fallback_unknown`,
          rankedCandidates: decision.rankedCandidates,
        };
        result = applyShot(fleet, fallback);
      }
    }

    const next = buildPolicyContext(fleet, result);
    policy.observeTransition?.(prev, decision, result, next);
    return { result, decision };
  };

  const humanAiTurn = (cur: MatchState): MatchState => {
    if (cur.winner) return cur;
    const { result, decision } = runPolicyTurn(
      cur.aiFleet,
      cur.humanAiLastResult,
      mirrorPolicy,
      'human-ai'
    );
    const winner = cur.aiFleet.complete ? 'human' : null;
    return {
      ...cur,
      humanTurn: winner ? true : false,
      winner,
      humanAiLastResult: result,
      aiDecisionLog: [
        {
          actor: 'human-ai' as const,
          turn: cur.aiFleet.turn,
          shot: decision.shot,
          confidence: decision.confidence,
          reason: decision.reason,
          result: result.kind,
          top: decision.rankedCandidates?.slice(0, 3),
        },
        ...cur.aiDecisionLog,
      ].slice(0, 30),
    };
  };

  const aiTurn = (cur: MatchState): MatchState => {
    if (cur.winner) return cur;
    const { result, decision } = runPolicyTurn(
      cur.humanFleet,
      cur.aiLastResult,
      activePolicy,
      'ai'
    );
    const winner = cur.humanFleet.complete ? 'ai' : null;
    return {
      ...cur,
      humanTurn: winner ? false : true,
      winner,
      aiLastResult: result,
      aiDecisionLog: [
        {
          actor: 'ai' as const,
          turn: cur.humanFleet.turn,
          shot: decision.shot,
          confidence: decision.confidence,
          reason: decision.reason,
          result: result.kind,
          top: decision.rankedCandidates?.slice(0, 3),
        },
        ...cur.aiDecisionLog,
      ].slice(0, 30),
    };
  };

  const onHumanShot = (coord: Coord): void => {
    setMatch((cur) => {
      if (!cur.humanTurn || cur.winner || aiVsAiMode) return cur;
      if (cur.aiFleet.publicBoard.cells[coord.y][coord.x] !== 'unknown') return cur;
      applyShot(cur.aiFleet, coord);
      const humanWon = cur.aiFleet.complete;
      const nextAfterHuman: MatchState = {
        ...cur,
        humanTurn: false,
        winner: humanWon ? 'human' : null,
      };
      if (humanWon) return nextAfterHuman;
      return aiTurn(nextAfterHuman);
    });
  };

  const stepAutoTurn = (): void => {
    setMatch((cur) => {
      if (cur.winner) return cur;
      if (cur.humanTurn) {
        return humanAiTurn(cur);
      }
      return aiTurn(cur);
    });
  };

  useEffect(() => {
    if (!aiVsAiMode || !isAutoPlaying) return;
    if (match.winner) {
      setIsAutoPlaying(false);
      return;
    }
    const delay = Math.max(80, autoPlayDelayMs);
    const id = window.setInterval(() => {
      stepAutoTurn();
    }, delay);
    return () => window.clearInterval(id);
  }, [aiVsAiMode, isAutoPlaying, match.winner, autoPlayDelayMs, useHybrid]);

  const runTraining = async (): Promise<void> => {
    setIsTraining(true);
    try {
      const artifacts = trainHybridPolicy({
        trainEpisodes: Math.max(200, trainEpisodes),
        benchmarkEpisodes: Math.max(100, benchmarkEpisodes),
      });
      setReport(artifacts.report);
    } finally {
      setIsTraining(false);
    }
  };

  return (
    <div className="min-h-full bg-slate-950 p-6 text-slate-100">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Battleship AI Lab</h1>
          <p className="mt-1 text-sm text-slate-400">
            Hybrid policy playground: hunt/target baseline + RL fine-tune.
          </p>
        </div>
        <button
          type="button"
          onClick={goToProjects}
          className="rounded-md border border-slate-700 px-3 py-2 text-sm hover:bg-slate-900"
        >
          Back to projects
        </button>
      </div>

      <div className="mb-4 flex gap-2">
        <button
          type="button"
          onClick={() => setLabMode('classic')}
          className={`rounded px-3 py-2 text-sm ${labMode === 'classic' ? 'bg-indigo-700 font-semibold' : 'border border-slate-700 hover:bg-slate-900'}`}
        >
          Classic Battleship
        </button>
        <button
          type="button"
          onClick={() => setLabMode('wall')}
          className={`rounded px-3 py-2 text-sm ${labMode === 'wall' ? 'bg-indigo-700 font-semibold' : 'border border-slate-700 hover:bg-slate-900'}`}
        >
          Wall Battleship
        </button>
      </div>

      {labMode === 'wall' ? (
        <WallBattleshipLab />
      ) : (
        <>
      <div className="mb-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <button
          type="button"
          onClick={resetMatch}
          className="rounded-md bg-emerald-700 px-3 py-2 text-sm font-semibold hover:bg-emerald-600"
        >
          New Match
        </button>
        <label className="flex items-center gap-2 rounded-md border border-slate-700 px-3 py-2 text-sm">
          <input
            type="checkbox"
            checked={useHybrid}
            onChange={(e) => setUseHybrid(e.target.checked)}
          />
          Use hybrid RL policy
        </label>
        <label className="flex items-center gap-2 rounded-md border border-slate-700 px-3 py-2 text-sm">
          <input
            type="checkbox"
            checked={aiVsAiMode}
            onChange={(e) => {
              const next = e.target.checked;
              setAiVsAiMode(next);
              if (!next) setIsAutoPlaying(false);
            }}
          />
          AI vs AI mode
        </label>
        <div className="flex items-center gap-2 rounded-md border border-slate-700 px-3 py-2 text-sm">
          <button
            type="button"
            disabled={!aiVsAiMode || !!match.winner}
            onClick={() => setIsAutoPlaying((v) => !v)}
            className="rounded border border-slate-600 px-2 py-1 text-xs hover:bg-slate-800 disabled:opacity-50"
          >
            {isAutoPlaying ? 'Pause' : 'Autoplay'}
          </button>
          <button
            type="button"
            disabled={!aiVsAiMode || !!match.winner}
            onClick={stepAutoTurn}
            className="rounded border border-slate-600 px-2 py-1 text-xs hover:bg-slate-800 disabled:opacity-50"
          >
            Step
          </button>
          <input
            type="number"
            min={80}
            step={20}
            value={autoPlayDelayMs}
            onChange={(e) => setAutoPlayDelayMs(Math.max(80, Number(e.target.value) || 80))}
            className="w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
            title="Autoplay delay (ms)"
          />
          <span className="text-xs text-slate-400">ms</span>
        </div>
        <div className="rounded-md border border-slate-700 px-3 py-2 text-sm">
          Winner:{' '}
          <span className="font-semibold">
            {match.winner ? match.winner.toUpperCase() : 'in progress'}
          </span>
        </div>
        <div className="rounded-md border border-slate-700 px-3 py-2 text-sm">
          Turn: <span className="font-semibold">{match.humanTurn ? 'HUMAN' : 'AI'}</span>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_1fr_380px]">
        <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <h2 className="mb-3 text-lg font-semibold">Enemy Fleet (you shoot here)</h2>
          <div className="grid grid-cols-10 gap-1">
            {match.aiFleet.publicBoard.cells.map((row, y) =>
              row.map((cell, x) => (
                <button
                  key={`enemy-${x}-${y}`}
                  type="button"
                  disabled={!match.humanTurn || !!match.winner || aiVsAiMode}
                  className={cellClass(cell, match.humanTurn && !match.winner)}
                  onClick={() => onHumanShot({ x, y })}
                  title={coordLabel({ x, y })}
                >
                  {coordLabel({ x, y })}
                </button>
              ))
            )}
          </div>
        </section>

        <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <h2 className="mb-3 text-lg font-semibold">Your Fleet (AI shooting)</h2>
          <div className="grid grid-cols-10 gap-1">
            {match.humanFleet.publicBoard.cells.map((row, y) =>
              row.map((cell, x) => (
                <div
                  key={`human-${x}-${y}`}
                  className={cellClass(cell, false)}
                  title={coordLabel({ x, y })}
                >
                  {coordLabel({ x, y })}
                </div>
              ))
            )}
          </div>
        </section>

        <section className="space-y-4">
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="mb-2 text-lg font-semibold">Training & Benchmark</h2>
            <div className="mb-3 grid grid-cols-2 gap-2 text-sm">
              <label className="flex flex-col gap-1">
                Train episodes
                <input
                  type="number"
                  min={200}
                  value={trainEpisodes}
                  onChange={(e) => setTrainEpisodes(Number(e.target.value))}
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1"
                />
              </label>
              <label className="flex flex-col gap-1">
                Benchmark episodes
                <input
                  type="number"
                  min={100}
                  value={benchmarkEpisodes}
                  onChange={(e) => setBenchmarkEpisodes(Number(e.target.value))}
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1"
                />
              </label>
            </div>
            <button
              type="button"
              onClick={runTraining}
              disabled={isTraining}
              className="w-full rounded-md bg-indigo-700 px-3 py-2 text-sm font-semibold hover:bg-indigo-600 disabled:opacity-50"
            >
              {isTraining ? 'Training...' : 'Train + benchmark hybrid policy'}
            </button>
            {report && (
              <div className="mt-3 space-y-2">
                <button
                  type="button"
                  onClick={() =>
                    downloadText(
                      `battleship_report_${Date.now()}.json`,
                      JSON.stringify(report, null, 2),
                      'application/json'
                    )
                  }
                  className="w-full rounded border border-slate-700 px-3 py-2 text-xs hover:bg-slate-800"
                >
                  Download report JSON
                </button>
                <button
                  type="button"
                  onClick={() =>
                    downloadText(
                      `battleship_report_${Date.now()}.md`,
                      reportMarkdown(report),
                      'text/markdown'
                    )
                  }
                  className="w-full rounded border border-slate-700 px-3 py-2 text-xs hover:bg-slate-800"
                >
                  Download report MD
                </button>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="mb-2 text-lg font-semibold">AI Reasoning Trace</h2>
            <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1 text-xs">
              {match.aiDecisionLog.length === 0 ? (
                <div className="text-slate-400">No AI turns yet.</div>
              ) : (
                match.aiDecisionLog.map((row, idx) => (
                  <div key={`${row.turn}-${idx}`} className="rounded border border-slate-700 p-2">
                    <div className="font-semibold">
                      {row.actor === 'ai' ? 'AI' : 'Mirror AI'} Turn {row.turn}: {coordLabel(row.shot)} {'->'} {row.result}
                    </div>
                    <div>confidence: {row.confidence.toFixed(2)}</div>
                    <div>reason: {row.reason}</div>
                    {row.top && row.top.length > 0 && (
                      <div className="mt-1 text-slate-300">
                        top candidates:{' '}
                        {row.top
                          .map((c) => `${coordLabel(c.coord)} (${c.score.toFixed(1)})`)
                          .join(', ')}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </section>
      </div>

      {report && (
        <section className="mt-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <h2 className="mb-3 text-lg font-semibold">Benchmark Metrics</h2>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-slate-300">
                  <th className="px-2 py-1">Policy</th>
                  <th className="px-2 py-1">Completion</th>
                  <th className="px-2 py-1">Avg shots</th>
                  <th className="px-2 py-1">P50</th>
                  <th className="px-2 py-1">P90</th>
                  <th className="px-2 py-1">Avg sink turn</th>
                </tr>
              </thead>
              <tbody>
                {report.metrics.map((row) => (
                  <tr key={row.policyId} className="border-t border-slate-800">
                    <td className="px-2 py-1">{row.policyId}</td>
                    <td className="px-2 py-1">{(row.completionRate * 100).toFixed(1)}%</td>
                    <td className="px-2 py-1">{row.avgShots.toFixed(2)}</td>
                    <td className="px-2 py-1">{row.p50Shots.toFixed(2)}</td>
                    <td className="px-2 py-1">{row.p90Shots.toFixed(2)}</td>
                    <td className="px-2 py-1">{row.avgSinkTurn.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      </>
      )}
    </div>
  );
}

