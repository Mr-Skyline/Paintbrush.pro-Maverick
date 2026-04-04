import { pointDistance } from '@/battleship/wallhunt/geometry';
import type { Point2D, WallHuntScoreConfig } from '@/battleship/wallhunt/types';

export const defaultWallScoreConfig = (): WallHuntScoreConfig => ({
  hitReward: 2.5,
  missPenalty: -2.0,
  outOfBoundsPenalty: -3.0,
  longJumpBonus: 1.6,
  longJumpMinDistancePx: 10,
  segmentPenalty: -0.5,
  completionBonus: 15,
});

export const longJumpBonus = (
  point: Point2D,
  prevValidPoint: Point2D | null,
  cfg: WallHuntScoreConfig
): boolean => {
  if (!prevValidPoint) return false;
  return pointDistance(point, prevValidPoint) > cfg.longJumpMinDistancePx;
};

