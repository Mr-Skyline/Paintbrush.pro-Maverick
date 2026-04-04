import { Coord, PolicyContext } from '@/battleship/types';

const keyOf = (c: Coord): string => `${c.x},${c.y}`;

const inBounds = (c: Coord, size: number): boolean =>
  c.x >= 0 && c.y >= 0 && c.x < size && c.y < size;

const orthogonal = (c: Coord): Coord[] => [
  { x: c.x + 1, y: c.y },
  { x: c.x - 1, y: c.y },
  { x: c.x, y: c.y + 1 },
  { x: c.x, y: c.y - 1 },
];

export const unknownCells = (ctx: PolicyContext): Coord[] => {
  const out: Coord[] = [];
  for (let y = 0; y < ctx.board.size; y += 1) {
    for (let x = 0; x < ctx.board.size; x += 1) {
      if (ctx.board.cells[y][x] === 'unknown') out.push({ x, y });
    }
  }
  return out;
};

export const unresolvedHitClusters = (ctx: PolicyContext): Coord[][] => {
  const hitSet = new Set<string>();
  for (let y = 0; y < ctx.board.size; y += 1) {
    for (let x = 0; x < ctx.board.size; x += 1) {
      if (ctx.board.cells[y][x] === 'hit') hitSet.add(`${x},${y}`);
    }
  }
  const visited = new Set<string>();
  const clusters: Coord[][] = [];
  for (const k of hitSet) {
    if (visited.has(k)) continue;
    const [sx, sy] = k.split(',').map(Number);
    const queue: Coord[] = [{ x: sx, y: sy }];
    const cluster: Coord[] = [];
    visited.add(k);
    while (queue.length > 0) {
      const cur = queue.shift()!;
      cluster.push(cur);
      for (const n of orthogonal(cur)) {
        const nk = keyOf(n);
        if (!inBounds(n, ctx.board.size)) continue;
        if (!hitSet.has(nk) || visited.has(nk)) continue;
        visited.add(nk);
        queue.push(n);
      }
    }
    clusters.push(cluster);
  }
  return clusters;
};

const candidateCells = (
  origin: Coord,
  axis: 'horizontal' | 'vertical',
  len: number
): Coord[] =>
  Array.from({ length: len }, (_, i) =>
    axis === 'horizontal'
      ? { x: origin.x + i, y: origin.y }
      : { x: origin.x, y: origin.y + i }
  );

export const placementHeatmap = (ctx: PolicyContext): number[][] => {
  const heat = Array.from({ length: ctx.board.size }, () =>
    Array.from({ length: ctx.board.size }, () => 0)
  );
  const clusters = unresolvedHitClusters(ctx);
  const forcedHits = new Set(clusters.flat().map(keyOf));

  for (const shipLen of ctx.remainingShips) {
    for (const axis of ['horizontal', 'vertical'] as const) {
      const maxX = axis === 'horizontal' ? ctx.board.size - shipLen : ctx.board.size - 1;
      const maxY = axis === 'vertical' ? ctx.board.size - shipLen : ctx.board.size - 1;
      for (let y = 0; y <= maxY; y += 1) {
        for (let x = 0; x <= maxX; x += 1) {
          const cells = candidateCells({ x, y }, axis, shipLen);
          let valid = true;
          let coversHits = forcedHits.size === 0;
          for (const c of cells) {
            const state = ctx.board.cells[c.y][c.x];
            if (state === 'miss' || state === 'sunk') {
              valid = false;
              break;
            }
            if (state === 'hit') coversHits = true;
          }
          if (!valid || !coversHits) continue;
          for (const c of cells) {
            if (ctx.board.cells[c.y][c.x] === 'unknown') {
              heat[c.y][c.x] += 1;
            }
          }
        }
      }
    }
  }
  return heat;
};

export const topScoredCells = (
  ctx: PolicyContext,
  scoreAt: (c: Coord) => number
): Array<{ coord: Coord; score: number }> =>
  unknownCells(ctx)
    .map((coord) => ({ coord, score: scoreAt(coord) }))
    .sort((a, b) => b.score - a.score);

