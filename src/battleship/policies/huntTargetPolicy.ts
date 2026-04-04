import { BattleshipPolicy, Coord, PolicyContext } from '@/battleship/types';
import {
  placementHeatmap,
  topScoredCells,
  unresolvedHitClusters,
  unknownCells,
} from '@/battleship/policies/utils';

const scoreTargetMode = (
  ctx: PolicyContext,
  cluster: Coord[]
): Array<{ coord: Coord; score: number; reason: string }> => {
  const unknown = new Set(unknownCells(ctx).map((c) => `${c.x},${c.y}`));
  const out: Array<{ coord: Coord; score: number; reason: string }> = [];
  if (cluster.length === 0) return out;

  const xs = cluster.map((c) => c.x);
  const ys = cluster.map((c) => c.y);
  const sameRow = ys.every((y) => y === ys[0]);
  const sameCol = xs.every((x) => x === xs[0]);

  const candidates: Coord[] = [];
  if (sameRow) {
    const y = ys[0];
    candidates.push({ x: Math.min(...xs) - 1, y }, { x: Math.max(...xs) + 1, y });
  } else if (sameCol) {
    const x = xs[0];
    candidates.push({ x, y: Math.min(...ys) - 1 }, { x, y: Math.max(...ys) + 1 });
  } else {
    for (const c of cluster) {
      candidates.push(
        { x: c.x + 1, y: c.y },
        { x: c.x - 1, y: c.y },
        { x: c.x, y: c.y + 1 },
        { x: c.x, y: c.y - 1 }
      );
    }
  }

  for (const c of candidates) {
    const k = `${c.x},${c.y}`;
    if (!unknown.has(k)) continue;
    let score = 100;
    if (sameRow || sameCol) score += 50;
    if ((c.x + c.y) % 2 === 0) score += 5;
    out.push({
      coord: c,
      score,
      reason: sameRow || sameCol ? 'target_line_extension' : 'target_adjacent_probe',
    });
  }
  return out.sort((a, b) => b.score - a.score);
};

export const createHuntTargetPolicy = (): BattleshipPolicy => ({
  id: 'hunt_target',
  decide(ctx: PolicyContext) {
    const clusters = unresolvedHitClusters(ctx).sort(
      (a, b) => b.length - a.length
    );
    if (clusters.length > 0) {
      const targetRank = scoreTargetMode(ctx, clusters[0]);
      if (targetRank.length > 0) {
        return {
          shot: targetRank[0].coord,
          confidence: 0.9,
          reason: targetRank[0].reason,
          rankedCandidates: targetRank.slice(0, 8).map((row) => ({
            coord: row.coord,
            score: row.score,
            reason: row.reason,
          })),
        };
      }
    }

    const heat = placementHeatmap(ctx);
    const ranked = topScoredCells(ctx, (c) => {
      const parity = (c.x + c.y) % 2 === 0 ? 0.35 : 0;
      return heat[c.y][c.x] + parity;
    });
    const best = ranked[0] ?? { coord: { x: 0, y: 0 }, score: 0 };
    return {
      shot: best.coord,
      confidence: 0.72,
      reason: 'hunt_heatmap_max',
      rankedCandidates: ranked.slice(0, 10).map((r) => ({
        coord: r.coord,
        score: r.score,
        reason: 'hunt_heatmap_rank',
      })),
    };
  },
});

