import { SeededRng } from '@/battleship/rng';
import { clampPointToMap, distanceToWall, pointDistance } from '@/battleship/wallhunt/geometry';
import type {
  LineSegment,
  Point2D,
  WallHuntAgent,
  WallHuntState,
} from '@/battleship/wallhunt/types';

class BaseWallAgent implements WallHuntAgent {
  id: string;
  generation: number;
  weights: Record<string, number>;
  protected rng: SeededRng;

  constructor(
    id: string,
    generation: number,
    weights: Record<string, number>,
    seed = 2026
  ) {
    this.id = id;
    this.generation = generation;
    this.weights = weights;
    this.rng = new SeededRng(seed);
  }

  proposeNextPoint(_state: WallHuntState): Point2D {
    return { x: 0, y: 0 };
  }

  proposeNextSegment(state: WallHuntState): LineSegment {
    const p = this.proposeNextPoint(state);
    return { a: p, b: p };
  }

  clone(nextId: string): WallHuntAgent {
    return new BaseWallAgent(
      nextId,
      this.generation + 1,
      { ...this.weights },
      Math.floor(this.rng.next() * 1_000_000)
    );
  }
}

export class RandomWallAgent extends BaseWallAgent {
  proposeNextPoint(state: WallHuntState): Point2D {
    return {
      x: Math.floor(this.rng.next() * state.map.width),
      y: Math.floor(this.rng.next() * state.map.height),
    };
  }

  proposeNextSegment(state: WallHuntState): LineSegment {
    return {
      a: this.proposeNextPoint(state),
      b: this.proposeNextPoint(state),
    };
  }

  clone(nextId: string): WallHuntAgent {
    return new RandomWallAgent(
      nextId,
      this.generation + 1,
      { ...this.weights },
      Math.floor(this.rng.next() * 1_000_000)
    );
  }
}

const nearestUnfinishedWall = (state: WallHuntState): string | null => {
  let best: { id: string; score: number } | null = null;
  for (const wall of state.map.walls) {
    if (state.completedWalls.has(wall.wallId)) continue;
    const coverage = state.coverageByWall[wall.wallId] ?? 0;
    const score = 1 - coverage;
    if (!best || score > best.score) {
      best = { id: wall.wallId, score };
    }
  }
  return best?.id ?? null;
};

export class FrontierWallAgent extends BaseWallAgent {
  private prevPoint: Point2D | null = null;

  proposeNextPoint(state: WallHuntState): Point2D {
    const targetWallId = nearestUnfinishedWall(state);
    const wall = state.map.walls.find((w) => w.wallId === targetWallId) ?? state.map.walls[0];
    const spread = Math.max(8, 20 / Math.max(0.3, this.weights.precision ?? 1));
    const explore = Math.max(0.02, Math.min(0.75, this.weights.exploration ?? 0.25));
    const jumpBias = Math.max(0.2, this.weights.longJumpBias ?? 1.0);

    let base = wall?.polyline[0] ?? {
      x: state.map.width / 2,
      y: state.map.height / 2,
    };
    if (this.prevPoint && this.rng.next() > explore) {
      base = this.prevPoint;
    } else if (wall) {
      const idx = Math.floor(this.rng.next() * wall.polyline.length);
      base = wall.polyline[Math.max(0, Math.min(wall.polyline.length - 1, idx))];
    }
    const jumpScale = this.rng.next() < 0.5 ? 1 : jumpBias;
    const out = {
      x: base.x + (this.rng.next() * 2 - 1) * spread * jumpScale,
      y: base.y + (this.rng.next() * 2 - 1) * spread * jumpScale,
    };
    const clamped = clampPointToMap(out, state.map.width, state.map.height);
    this.prevPoint = clamped;
    return clamped;
  }

  proposeNextSegment(state: WallHuntState): LineSegment {
    const targetWallId = nearestUnfinishedWall(state);
    const wall = state.map.walls.find((w) => w.wallId === targetWallId) ?? state.map.walls[0];
    if (wall && wall.polyline.length >= 2) {
      const idx = Math.floor(this.rng.next() * (wall.polyline.length - 1));
      const a = wall.polyline[idx];
      const b = wall.polyline[idx + 1];
      const spread = Math.max(4, 12 / Math.max(0.4, this.weights.precision ?? 1));
      const jitter = (p: Point2D): Point2D => ({
        x: p.x + (this.rng.next() * 2 - 1) * spread,
        y: p.y + (this.rng.next() * 2 - 1) * spread,
      });
      return {
        a: clampPointToMap(jitter(a), state.map.width, state.map.height),
        b: clampPointToMap(jitter(b), state.map.width, state.map.height),
      };
    }
    return {
      a: this.proposeNextPoint(state),
      b: this.proposeNextPoint(state),
    };
  }

  clone(nextId: string): WallHuntAgent {
    return new FrontierWallAgent(
      nextId,
      this.generation + 1,
      { ...this.weights },
      Math.floor(this.rng.next() * 1_000_000)
    );
  }
}

export class GreedyWallAgent extends BaseWallAgent {
  proposeNextPoint(state: WallHuntState): Point2D {
    const precision = Math.max(0.3, this.weights.precision ?? 1);
    const jitter = 10 / precision;
    const prev = state.predictions[state.predictions.length - 1];
    if (!prev) {
      const firstWall = state.map.walls[0];
      const p = firstWall?.polyline[0] ?? { x: state.map.width / 2, y: state.map.height / 2 };
      return clampPointToMap(p, state.map.width, state.map.height);
    }
    let bestPoint = prev;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const wall of state.map.walls) {
      if (state.completedWalls.has(wall.wallId)) continue;
      const d = distanceToWall(prev, wall);
      if (d < bestDistance) {
        bestDistance = d;
        const nearest = wall.polyline.reduce((acc, c) =>
          pointDistance(c, prev) < pointDistance(acc, prev) ? c : acc
        );
        bestPoint = nearest;
      }
    }
    return clampPointToMap(
      {
        x: bestPoint.x + (this.rng.next() * 2 - 1) * jitter,
        y: bestPoint.y + (this.rng.next() * 2 - 1) * jitter,
      },
      state.map.width,
      state.map.height
    );
  }

  proposeNextSegment(state: WallHuntState): LineSegment {
    const precision = Math.max(0.3, this.weights.precision ?? 1);
    const jitter = 8 / precision;
    let bestWall = state.map.walls[0];
    let bestDist = Number.POSITIVE_INFINITY;
    const prev = state.predictions[state.predictions.length - 1] ?? {
      x: state.map.width / 2,
      y: state.map.height / 2,
    };
    for (const wall of state.map.walls) {
      if (state.completedWalls.has(wall.wallId)) continue;
      const d = distanceToWall(prev, wall);
      if (d < bestDist) {
        bestDist = d;
        bestWall = wall;
      }
    }
    if (!bestWall || bestWall.polyline.length < 2) {
      return { a: this.proposeNextPoint(state), b: this.proposeNextPoint(state) };
    }
    let bestIdx = 0;
    let bestSegDist = Number.POSITIVE_INFINITY;
    for (let i = 0; i < bestWall.polyline.length - 1; i += 1) {
      const a = bestWall.polyline[i];
      const b = bestWall.polyline[i + 1];
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const d = pointDistance(mid, prev);
      if (d < bestSegDist) {
        bestSegDist = d;
        bestIdx = i;
      }
    }
    const sa = bestWall.polyline[bestIdx];
    const sb = bestWall.polyline[bestIdx + 1];
    const j = (p: Point2D): Point2D => ({
      x: p.x + (this.rng.next() * 2 - 1) * jitter,
      y: p.y + (this.rng.next() * 2 - 1) * jitter,
    });
    return {
      a: clampPointToMap(j(sa), state.map.width, state.map.height),
      b: clampPointToMap(j(sb), state.map.width, state.map.height),
    };
  }

  clone(nextId: string): WallHuntAgent {
    return new GreedyWallAgent(
      nextId,
      this.generation + 1,
      { ...this.weights },
      Math.floor(this.rng.next() * 1_000_000)
    );
  }
}

export const createSeedPopulation = (
  populationSize: number
): WallHuntAgent[] => {
  const out: WallHuntAgent[] = [];
  const baseWeights = {
    precision: 1,
    exploration: 0.25,
    longJumpBias: 1,
    clickSigma: 2.5,
  };
  for (let i = 0; i < populationSize; i += 1) {
    if (i % 3 === 0) {
      out.push(
        new FrontierWallAgent(`frontier-${i + 1}`, 0, { ...baseWeights }, 1000 + i)
      );
    } else if (i % 3 === 1) {
      out.push(new GreedyWallAgent(`greedy-${i + 1}`, 0, { ...baseWeights }, 2000 + i));
    } else {
      out.push(new RandomWallAgent(`random-${i + 1}`, 0, { ...baseWeights }, 3000 + i));
    }
  }
  return out;
};

