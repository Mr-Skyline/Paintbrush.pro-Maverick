import { createHuntTargetPolicy } from '@/battleship/policies/huntTargetPolicy';
import { createRandomPolicy } from '@/battleship/policies/randomPolicy';
import { RlHybridPolicy } from '@/battleship/policies/rlHybridPolicy';
import { createSimpleHuntPolicy } from '@/battleship/policies/simpleHuntPolicy';
import { runBenchmark, runEpisode } from '@/battleship/simulator';
import { BattleshipPolicy } from '@/battleship/types';

export interface TrainingReport {
  generatedAt: string;
  trainEpisodes: number;
  benchmarkEpisodes: number;
  metrics: Array<{
    policyId: string;
    completionRate: number;
    avgShots: number;
    p50Shots: number;
    p90Shots: number;
    avgSinkTurn: number;
  }>;
  modelSnapshot: Record<string, { qValues: number[]; visits: number[] }>;
}

export interface TrainedHybridArtifacts {
  policy: BattleshipPolicy;
  report: TrainingReport;
}

export const trainHybridPolicy = (opts?: {
  trainEpisodes?: number;
  benchmarkEpisodes?: number;
  seedStart?: number;
}): TrainedHybridArtifacts => {
  const trainEpisodes = opts?.trainEpisodes ?? 1200;
  const benchmarkEpisodes = opts?.benchmarkEpisodes ?? 250;
  const seedStart = opts?.seedStart ?? 50000;

  const hybrid = new RlHybridPolicy({ seed: seedStart });
  for (let i = 0; i < trainEpisodes; i += 1) {
    runEpisode({
      policy: hybrid,
      seed: seedStart + i,
      maxTurns: 150,
    });
  }

  const policies: Array<{ id: string; factory: () => BattleshipPolicy }> = [
    { id: 'random', factory: () => createRandomPolicy(seedStart + 1) },
    { id: 'simple_hunt_target', factory: () => createSimpleHuntPolicy() },
    { id: 'hunt_target', factory: () => createHuntTargetPolicy() },
    {
      id: 'hybrid_rl',
      factory: () => {
        // Use the trained policy as-is for benchmark continuity.
        return hybrid;
      },
    },
  ];

  const metrics = policies.map((row, idx) =>
    runBenchmark({
      policyFactory: row.factory,
      episodes: benchmarkEpisodes,
      seedStart: seedStart + 100000 + idx * benchmarkEpisodes,
    }).metrics
  );

  return {
    policy: hybrid,
    report: {
      generatedAt: new Date().toISOString(),
      trainEpisodes,
      benchmarkEpisodes,
      metrics,
      modelSnapshot: hybrid.snapshot(),
    },
  };
};

