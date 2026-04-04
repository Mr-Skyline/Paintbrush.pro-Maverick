import type { WallHuntAgent } from '@/battleship/wallhunt/types';

const mutateWeight = (value: number, variance = 0.18): number => {
  const delta = (Math.random() * 2 - 1) * variance;
  return Math.max(0.02, value + delta);
};

export const spawnNextGeneration = (opts: {
  winners: WallHuntAgent[];
  populationSize: number;
  mutationRate: number;
}): WallHuntAgent[] => {
  const winners = opts.winners.slice();
  if (winners.length === 0) return [];
  const out: WallHuntAgent[] = [];
  let idx = 0;
  while (out.length < opts.populationSize) {
    const base = winners[idx % winners.length];
    const child = base.clone(`${base.id}-g${base.generation + 1}-${out.length + 1}`);
    if (Math.random() < opts.mutationRate) {
      child.weights = {
        ...child.weights,
        precision: mutateWeight(child.weights.precision ?? 1, 0.2),
        exploration: mutateWeight(child.weights.exploration ?? 0.25, 0.1),
        longJumpBias: mutateWeight(child.weights.longJumpBias ?? 1.0, 0.25),
        clickSigma: mutateWeight(child.weights.clickSigma ?? 2.5, 0.5),
      };
    }
    out.push(child);
    idx += 1;
  }
  return out;
};

