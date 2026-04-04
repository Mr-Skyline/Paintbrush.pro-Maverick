import {
  applyShot,
  buildPolicyContext,
  createGame,
} from '@/battleship/engine';
import {
  BattleshipPolicy,
  EpisodeSummary,
  ShotResult,
} from '@/battleship/types';

export const runEpisode = (opts: {
  policy: BattleshipPolicy;
  seed: number;
  maxTurns?: number;
}): EpisodeSummary => {
  const game = createGame({ seed: opts.seed });
  const maxTurns = opts.maxTurns ?? 150;
  let lastResult: ShotResult | null = null;

  const trace: EpisodeSummary['trace'] = [];
  let hits = 0;
  let misses = 0;
  const sinkTurns: number[] = [];

  while (!game.complete && game.turn < maxTurns) {
    const prevCtx = buildPolicyContext(game, lastResult);
    const decision = opts.policy.decide(prevCtx);
    const result = applyShot(game, decision.shot);
    const nextCtx = buildPolicyContext(game, result);
    opts.policy.observeTransition?.(prevCtx, decision, result, nextCtx);
    lastResult = result;

    if (result.kind === 'hit' || result.kind === 'sunk') hits += 1;
    if (result.kind === 'miss') misses += 1;
    if (result.kind === 'sunk') sinkTurns.push(game.turn);
    trace.push({
      turn: game.turn,
      shot: decision.shot,
      result: result.kind,
      confidence: decision.confidence,
      reason: decision.reason,
    });
  }

  return {
    policyId: opts.policy.id,
    seed: opts.seed,
    shots: game.turn,
    hits,
    misses,
    sunkCount: game.sunkShipIds.size,
    complete: game.complete,
    sinkTurns,
    trace,
  };
};

export interface BenchmarkMetrics {
  policyId: string;
  episodes: number;
  completionRate: number;
  avgShots: number;
  p50Shots: number;
  p90Shots: number;
  avgSinkTurn: number;
}

const percentile = (vals: number[], p: number): number => {
  if (vals.length === 0) return 0;
  const sorted = vals.slice().sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.floor(p * sorted.length)));
  return sorted[idx];
};

export const runBenchmark = (opts: {
  policyFactory: () => BattleshipPolicy;
  episodes: number;
  seedStart?: number;
}): { metrics: BenchmarkMetrics; episodes: EpisodeSummary[] } => {
  const seedStart = opts.seedStart ?? 1000;
  const episodes: EpisodeSummary[] = [];
  for (let i = 0; i < opts.episodes; i += 1) {
    const policy = opts.policyFactory();
    episodes.push(runEpisode({ policy, seed: seedStart + i }));
  }

  const shots = episodes.map((e) => e.shots);
  const complete = episodes.filter((e) => e.complete).length;
  const sinkTurns = episodes.flatMap((e) => e.sinkTurns);
  return {
    metrics: {
      policyId: episodes[0]?.policyId ?? 'unknown',
      episodes: opts.episodes,
      completionRate: complete / Math.max(1, opts.episodes),
      avgShots:
        shots.reduce((sum, x) => sum + x, 0) / Math.max(1, shots.length),
      p50Shots: percentile(shots, 0.5),
      p90Shots: percentile(shots, 0.9),
      avgSinkTurn:
        sinkTurns.reduce((sum, x) => sum + x, 0) / Math.max(1, sinkTurns.length),
    },
    episodes,
  };
};

