import type { LineSegment, Point2D, WallDefinition } from '@/battleship/wallhunt/types';

export const clampPointToMap = (
  p: Point2D,
  width: number,
  height: number
): Point2D => ({
  x: Math.max(0, Math.min(width - 1, p.x)),
  y: Math.max(0, Math.min(height - 1, p.y)),
});

export const pointDistance = (a: Point2D, b: Point2D): number =>
  Math.hypot(a.x - b.x, a.y - b.y);

export const pointToSegmentDistance = (
  p: Point2D,
  a: Point2D,
  b: Point2D
): number => {
  const abx = b.x - a.x;
  const aby = b.y - a.y;
  const apx = p.x - a.x;
  const apy = p.y - a.y;
  const ab2 = abx * abx + aby * aby;
  if (ab2 <= 1e-9) return pointDistance(p, a);
  const t = Math.max(0, Math.min(1, (apx * abx + apy * aby) / ab2));
  const proj = { x: a.x + abx * t, y: a.y + aby * t };
  return pointDistance(p, proj);
};

export const isPointInsideMap = (
  p: Point2D,
  width: number,
  height: number
): boolean => p.x >= 0 && p.y >= 0 && p.x < width && p.y < height;

export const distanceToWall = (p: Point2D, wall: WallDefinition): number => {
  if (wall.polyline.length === 0) return Number.POSITIVE_INFINITY;
  if (wall.polyline.length === 1) return pointDistance(p, wall.polyline[0]);
  let best = Number.POSITIVE_INFINITY;
  for (let i = 0; i < wall.polyline.length - 1; i += 1) {
    best = Math.min(
      best,
      pointToSegmentDistance(p, wall.polyline[i], wall.polyline[i + 1])
    );
  }
  return best;
};

export const hitWall = (p: Point2D, wall: WallDefinition): boolean =>
  distanceToWall(p, wall) <= wall.tolerancePx;

export const segmentLength = (s: LineSegment): number => pointDistance(s.a, s.b);

export const segmentMidpoint = (s: LineSegment): Point2D => ({
  x: (s.a.x + s.b.x) / 2,
  y: (s.a.y + s.b.y) / 2,
});

export const segmentAngleRad = (s: LineSegment): number =>
  Math.atan2(s.b.y - s.a.y, s.b.x - s.a.x);

const absAngleDelta = (a: number, b: number): number => {
  let d = Math.abs(a - b);
  while (d > Math.PI) d = Math.abs(d - Math.PI * 2);
  return Math.min(d, Math.abs(Math.PI - d));
};

export const segmentDistanceScore = (
  predicted: LineSegment,
  target: LineSegment
): { centerDist: number; endpointDist: number; angleDelta: number; lengthDelta: number } => {
  const mp = segmentMidpoint(predicted);
  const mt = segmentMidpoint(target);
  const centerDist = pointDistance(mp, mt);
  const endpointDist = Math.min(
    pointDistance(predicted.a, target.a) + pointDistance(predicted.b, target.b),
    pointDistance(predicted.a, target.b) + pointDistance(predicted.b, target.a)
  ) / 2;
  const angleDelta = absAngleDelta(segmentAngleRad(predicted), segmentAngleRad(target));
  const lengthDelta = Math.abs(segmentLength(predicted) - segmentLength(target));
  return { centerDist, endpointDist, angleDelta, lengthDelta };
};

export const wallSegments = (wall: WallDefinition): LineSegment[] => {
  const out: LineSegment[] = [];
  for (let i = 0; i < wall.polyline.length - 1; i += 1) {
    out.push({
      a: wall.polyline[i],
      b: wall.polyline[i + 1],
    });
  }
  return out;
};

const sampleSegment = (a: Point2D, b: Point2D, spacing: number): Point2D[] => {
  const dist = pointDistance(a, b);
  if (dist <= 1e-6) return [a];
  const steps = Math.max(1, Math.ceil(dist / Math.max(2, spacing)));
  return Array.from({ length: steps + 1 }, (_, idx) => {
    const t = idx / steps;
    return {
      x: a.x + (b.x - a.x) * t,
      y: a.y + (b.y - a.y) * t,
    };
  });
};

export const sampleWallPoints = (
  wall: WallDefinition,
  spacingPx = 10
): Point2D[] => {
  if (wall.polyline.length <= 1) return wall.polyline.slice();
  const out: Point2D[] = [];
  for (let i = 0; i < wall.polyline.length - 1; i += 1) {
    const pts = sampleSegment(wall.polyline[i], wall.polyline[i + 1], spacingPx);
    if (i > 0 && pts.length > 0) pts.shift();
    out.push(...pts);
  }
  return out;
};

