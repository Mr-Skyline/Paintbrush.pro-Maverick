import { SeededRng } from '@/battleship/rng';
import {
  BattleshipPolicy,
  PolicyContext,
  PolicyDecision,
  ShotResult,
} from '@/battleship/types';
import { createHuntTargetPolicy } from '@/battleship/policies/huntTargetPolicy';

interface BanditCell {
  qValues: number[];
  visits: number[];
}

const getBucket = (ctx: PolicyContext): string => {
  const hitCount = ctx.board.cells.flat().filter((c) => c === 'hit').length;
  const remaining = [...ctx.remainingShips].sort((a, b) => b - a).join('-');
  const turnBucket = Math.min(6, Math.floor(ctx.turn / 8));
  return `t${turnBucket}|h${Math.min(5, hitCount)}|r${remaining}`;
};

const ensureBanditCell = (
  table: Map<string, BanditCell>,
  bucket: string,
  actions: number
): BanditCell => {
  const found = table.get(bucket);
  if (found) return found;
  const created: BanditCell = {
    qValues: Array.from({ length: actions }, () => 0),
    visits: Array.from({ length: actions }, () => 0),
  };
  table.set(bucket, created);
  return created;
};

const rewardFor = (result: ShotResult): number => {
  if (result.kind === 'sunk') return 6;
  if (result.kind === 'hit') return 2;
  if (result.kind === 'miss') return -1;
  return -1.5;
};

export class RlHybridPolicy implements BattleshipPolicy {
  readonly id = 'hybrid_rl';

  private readonly baseline = createHuntTargetPolicy();

  private readonly table = new Map<string, BanditCell>();

  private readonly rng: SeededRng;

  private readonly actionCount: number;

  private readonly learningRate: number;

  private readonly discount: number;

  private readonly epsilon: number;

  private readonly minVisitForTrust: number;

  constructor(opts?: {
    seed?: number;
    actionCount?: number;
    learningRate?: number;
    discount?: number;
    epsilon?: number;
    minVisitForTrust?: number;
  }) {
    this.rng = new SeededRng(opts?.seed ?? 20260404);
    this.actionCount = opts?.actionCount ?? 4;
    this.learningRate = opts?.learningRate ?? 0.16;
    this.discount = opts?.discount ?? 0.9;
    this.epsilon = opts?.epsilon ?? 0.15;
    this.minVisitForTrust = opts?.minVisitForTrust ?? 10;
  }

  decide(ctx: PolicyContext): PolicyDecision {
    const base = this.baseline.decide(ctx);
    const ranked = base.rankedCandidates ?? [
      { coord: base.shot, score: 1, reason: base.reason },
    ];
    const top = ranked.slice(0, this.actionCount);
    const bucket = getBucket(ctx);
    const cell = ensureBanditCell(this.table, bucket, this.actionCount);

    let chosenAction = 0;
    if (this.rng.next() < this.epsilon) {
      chosenAction = this.rng.nextInt(Math.max(1, top.length));
    } else {
      const padded = cell.qValues.slice(0, top.length);
      let best = -Infinity;
      for (let i = 0; i < padded.length; i += 1) {
        if (padded[i] > best) {
          best = padded[i];
          chosenAction = i;
        }
      }
    }

    const bestVisitCount = cell.visits[chosenAction] ?? 0;
    const trustable = bestVisitCount >= this.minVisitForTrust;
    const target = top[chosenAction] ?? top[0] ?? ranked[0];
    const useFallback = !trustable && chosenAction !== 0;
    const selected = useFallback ? top[0] ?? ranked[0] : target;

    return {
      shot: selected.coord,
      confidence: trustable ? 0.84 : 0.58,
      reason: useFallback
        ? 'hybrid_fallback_low_rl_confidence'
        : `hybrid_rl_action_${chosenAction}`,
      rankedCandidates: ranked.slice(0, 10).map((r) => ({
        coord: r.coord,
        score: r.score,
        reason: r.reason,
      })),
    };
  }

  observeTransition(
    prev: PolicyContext,
    decision: PolicyDecision,
    result: ShotResult,
    next: PolicyContext
  ): void {
    const bucket = getBucket(prev);
    const nextBucket = getBucket(next);
    const prevCell = ensureBanditCell(this.table, bucket, this.actionCount);
    const nextCell = ensureBanditCell(this.table, nextBucket, this.actionCount);

    const actionIdx = (() => {
      const ranked = decision.rankedCandidates ?? [];
      for (let i = 0; i < Math.min(ranked.length, this.actionCount); i += 1) {
        const c = ranked[i].coord;
        if (c.x === decision.shot.x && c.y === decision.shot.y) return i;
      }
      return 0;
    })();

    const reward = rewardFor(result);
    const nextBest = Math.max(...nextCell.qValues);
    const oldQ = prevCell.qValues[actionIdx] ?? 0;
    const updated =
      oldQ + this.learningRate * (reward + this.discount * nextBest - oldQ);
    prevCell.qValues[actionIdx] = updated;
    prevCell.visits[actionIdx] = (prevCell.visits[actionIdx] ?? 0) + 1;
  }

  snapshot(): Record<string, { qValues: number[]; visits: number[] }> {
    const out: Record<string, { qValues: number[]; visits: number[] }> = {};
    for (const [k, v] of this.table.entries()) {
      out[k] = { qValues: v.qValues.slice(), visits: v.visits.slice() };
    }
    return out;
  }
}

