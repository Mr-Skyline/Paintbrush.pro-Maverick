import {
  clampPointToMap,
  isPointInsideMap,
  pointDistance,
  segmentDistanceScore,
  segmentMidpoint,
  wallSegments,
} from '@/battleship/wallhunt/geometry';
import { defaultWallScoreConfig, longJumpBonus } from '@/battleship/wallhunt/scoring';
import type {
  Point2D,
  WallEpisodeResult,
  WallHuntAgent,
  WallInteractionConfig,
  WallHuntMap,
  WallHuntScoreConfig,
  WallHuntState,
  WallStepEvent,
} from '@/battleship/wallhunt/types';

const pointInRect = (
  p: Point2D,
  rect: { x: number; y: number; width: number; height: number }
): boolean =>
  p.x >= rect.x &&
  p.y >= rect.y &&
  p.x <= rect.x + rect.width &&
  p.y <= rect.y + rect.height;

const nearestButtonDistance = (p: Point2D, cfg: WallInteractionConfig): number => {
  if (cfg.buttonTargets.length === 0) return Number.POSITIVE_INFINITY;
  return cfg.buttonTargets.reduce(
    (best, b) => Math.min(best, pointDistance(p, b.center)),
    Number.POSITIVE_INFINITY
  );
};

const buildInitialState = (
  map: WallHuntMap,
  maxTurns: number
): WallHuntState => {
  const coverageByWall: Record<string, number> = {};
  const segmentsByWall: Record<string, number> = {};
  for (const wall of map.walls) {
    coverageByWall[wall.wallId] = 0;
    segmentsByWall[wall.wallId] = 0;
  }
  return {
    map,
    turn: 0,
    maxTurns,
    predictions: [],
    totalScore: 0,
    completedWalls: new Set<string>(),
    coverageByWall,
    segmentsByWall,
    activeWallId: null,
    done: false,
  };
};

export const runWallEpisode = (opts: {
  map: WallHuntMap;
  agent: WallHuntAgent;
  maxTurns?: number;
  scoreConfig?: WallHuntScoreConfig;
  interactionConfig?: WallInteractionConfig;
}): WallEpisodeResult => {
  const cfg = opts.scoreConfig ?? defaultWallScoreConfig();
  const maxTurns = opts.maxTurns ?? 200;
  const state = buildInitialState(opts.map, maxTurns);
  const trace: WallStepEvent[] = [];
  const matchedWallSegments: Record<string, Set<number>> = {};
  let prevValidPoint: Point2D | null = null;
  let bonusCount = 0;
  let invalidCount = 0;
  let invalidOutsideArenaCount = 0;
  let invalidUiCount = 0;
  let uiClickValidCount = 0;

  for (const wall of opts.map.walls) {
    matchedWallSegments[wall.wallId] = new Set<number>();
  }

  while (!state.done && state.turn < state.maxTurns) {
    const segRaw = opts.agent.proposeNextSegment
      ? opts.agent.proposeNextSegment(state)
      : {
          a: opts.agent.proposeNextPoint(state),
          b: opts.agent.proposeNextPoint(state),
        };
    const seg = {
      a: clampPointToMap(segRaw.a, state.map.width, state.map.height),
      b: clampPointToMap(segRaw.b, state.map.width, state.map.height),
    };
    const point = segmentMidpoint(seg);
    const inBounds =
      isPointInsideMap(seg.a, state.map.width, state.map.height) &&
      isPointInsideMap(seg.b, state.map.width, state.map.height);
    const insideArena = opts.interactionConfig
      ? pointInRect(seg.a, opts.interactionConfig.arenaRect) &&
        pointInRect(seg.b, opts.interactionConfig.arenaRect)
      : true;
    let uiAction = false;
    let uiActionValid = false;
    let hitWallId: string | null = null;
    let validHit = false;
    let scoreDelta = 0;
    let reason = '';

    if (!inBounds) {
      invalidCount += 1;
      scoreDelta += cfg.outOfBoundsPenalty;
      reason = 'out_of_bounds';
    } else if (!insideArena && opts.interactionConfig) {
      uiAction = true;
      const inAnnotatedZone = opts.interactionConfig.uiClickableZones.some((z) =>
        pointInRect(point, z.rect)
      );
      const inButtonZone = nearestButtonDistance(point, opts.interactionConfig) <= 18;
      if (opts.interactionConfig.policy === 'strict-no-ui') {
        uiActionValid = false;
      } else if (opts.interactionConfig.policy === 'buttons-only') {
        uiActionValid = inButtonZone;
      } else {
        uiActionValid = inButtonZone || inAnnotatedZone;
      }
      if (uiActionValid) {
        uiClickValidCount += 1;
        scoreDelta += cfg.missPenalty * 0.25;
        reason = inButtonZone ? 'ui_button_click' : 'ui_zone_click';
      } else {
        invalidCount += 1;
        invalidOutsideArenaCount += 1;
        invalidUiCount += 1;
        scoreDelta += cfg.missPenalty;
        reason = 'invalid_outside_arena';
      }
    } else {
      let bestMatch:
        | {
            wallId: string;
            segmentIdx: number;
            score: number;
          }
        | null = null;
      for (const wall of state.map.walls) {
        const targets = wallSegments(wall);
        for (let i = 0; i < targets.length; i += 1) {
          const metric = segmentDistanceScore(seg, targets[i]);
          const within =
            metric.centerDist <= wall.tolerancePx * 1.4 &&
            metric.endpointDist <= wall.tolerancePx * 1.8 &&
            metric.angleDelta <= 0.5;
          if (!within) continue;
          const score =
            metric.centerDist +
            metric.endpointDist +
            metric.lengthDelta * 0.25 +
            metric.angleDelta * 20;
          if (!bestMatch || score < bestMatch.score) {
            bestMatch = {
              wallId: wall.wallId,
              segmentIdx: i,
              score,
            };
          }
        }
      }

      if (!bestMatch) {
        invalidCount += 1;
        scoreDelta += cfg.missPenalty;
        reason = 'miss_no_segment_match';
      } else {
        const wall = state.map.walls.find((w) => w.wallId === bestMatch.wallId)!;
        hitWallId = bestMatch.wallId;
        validHit = true;
        scoreDelta += cfg.hitReward;
        reason = `hit_segment_${wall.wallId}`;

        if (state.activeWallId !== wall.wallId) {
          state.activeWallId = wall.wallId;
          state.segmentsByWall[wall.wallId] += 1;
          scoreDelta += cfg.segmentPenalty;
        } else if (prevValidPoint && pointDistance(prevValidPoint, point) > 24) {
          state.segmentsByWall[wall.wallId] += 1;
          scoreDelta += cfg.segmentPenalty;
        }

        matchedWallSegments[wall.wallId].add(bestMatch.segmentIdx);
        const totalSegs = Math.max(1, wallSegments(wall).length);
        const coverage = matchedWallSegments[wall.wallId].size / totalSegs;
        state.coverageByWall[wall.wallId] = coverage;

        if (
          !state.completedWalls.has(wall.wallId) &&
          coverage >= wall.requiredCoverage &&
          state.segmentsByWall[wall.wallId] <= wall.maxSegments
        ) {
          state.completedWalls.add(wall.wallId);
          scoreDelta += cfg.completionBonus;
          reason += '_wall_completed';
        }

        if (longJumpBonus(point, prevValidPoint, cfg)) {
          bonusCount += 1;
          scoreDelta += cfg.longJumpBonus;
          reason += '_long_jump_bonus';
        }
        prevValidPoint = point;
      }
    }

    state.turn += 1;
    state.predictions.push(point);
    state.totalScore += scoreDelta;
    if (state.completedWalls.size === state.map.walls.length) {
      state.done = true;
    }
    if (state.turn >= state.maxTurns) {
      state.done = true;
    }

    const evt: WallStepEvent = {
      turn: state.turn,
      point,
      segment: seg,
      inBounds,
      insideArena,
      hitWallId,
      validHit,
      uiAction,
      uiActionValid,
      bonusAwarded: reason.includes('long_jump_bonus'),
      scoreDelta,
      totalScore: state.totalScore,
      reason,
    };
    trace.push(evt);
    opts.agent.observeStep?.(state, evt);
  }

  const segmentsTotal = Object.values(state.segmentsByWall).reduce(
    (sum, x) => sum + x,
    0
  );
  return {
    mapId: state.map.mapId,
    agentId: opts.agent.id,
    mode: 'warmup',
    score: state.totalScore,
    turns: state.turn,
    completedWallCount: state.completedWalls.size,
    completedWalls: [...state.completedWalls],
    segmentsTotal,
    invalidRate: invalidCount / Math.max(1, state.turn),
    invalidOutsideArenaCount,
    invalidUiCount,
    uiClickValidCount,
    longJumpBonusCount: bonusCount,
    trace,
  };
};

