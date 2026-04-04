export interface Point2D {
  x: number;
  y: number;
}

export interface Rect2D {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface LineSegment {
  a: Point2D;
  b: Point2D;
}

export interface UiClickableZone {
  id: string;
  label: string;
  rect: Rect2D;
}

export type WallInteractionPolicy = 'buttons-only' | 'annotated-ui' | 'strict-no-ui';

export interface WallInteractionConfig {
  arenaRect: Rect2D;
  uiClickableZones: UiClickableZone[];
  buttonTargets: OstButtonTarget[];
  policy: WallInteractionPolicy;
}

export interface WallDefinition {
  wallId: string;
  className: string;
  polyline: Point2D[];
  tolerancePx: number;
  maxSegments: number;
  requiredCoverage: number;
}

export interface WallHuntMap {
  mapId: string;
  imagePath?: string;
  backgroundUrl?: string;
  width: number;
  height: number;
  walls: WallDefinition[];
}

export interface WallHuntScoreConfig {
  hitReward: number;
  missPenalty: number;
  outOfBoundsPenalty: number;
  longJumpBonus: number;
  longJumpMinDistancePx: number;
  segmentPenalty: number;
  completionBonus: number;
}

export interface WallHuntState {
  map: WallHuntMap;
  turn: number;
  maxTurns: number;
  predictions: Point2D[];
  totalScore: number;
  completedWalls: Set<string>;
  coverageByWall: Record<string, number>;
  segmentsByWall: Record<string, number>;
  activeWallId: string | null;
  done: boolean;
}

export interface WallStepEvent {
  turn: number;
  point: Point2D;
  segment: LineSegment;
  inBounds: boolean;
  insideArena: boolean;
  hitWallId: string | null;
  validHit: boolean;
  uiAction: boolean;
  uiActionValid: boolean;
  bonusAwarded: boolean;
  scoreDelta: number;
  totalScore: number;
  reason: string;
}

export interface WallEpisodeResult {
  mapId: string;
  agentId: string;
  mode: QualificationMode;
  score: number;
  turns: number;
  completedWallCount: number;
  completedWalls: string[];
  segmentsTotal: number;
  invalidRate: number;
  invalidOutsideArenaCount: number;
  invalidUiCount: number;
  uiClickValidCount: number;
  longJumpBonusCount: number;
  trace: WallStepEvent[];
}

export interface WallHuntAgent {
  id: string;
  generation: number;
  weights: Record<string, number>;
  proposeNextPoint(state: WallHuntState): Point2D;
  proposeNextSegment?(state: WallHuntState): LineSegment;
  observeStep?(state: WallHuntState, event: WallStepEvent): void;
  clone(nextId: string): WallHuntAgent;
}

export type QualificationMode = 'warmup' | 'ranked';

export interface OstButtonTarget {
  id: string;
  label: string;
  center: Point2D;
  tolerancePx: number;
}

export interface QualificationAttempt {
  buttonId: string;
  expected: Point2D;
  predicted: Point2D;
  offsetPx: number;
  hit: boolean;
}

export interface QualificationResult {
  mode: QualificationMode;
  agentId: string;
  pass: boolean;
  minHitsRequired: number;
  totalHits: number;
  meanOffsetPx: number;
  maxOffsetPx: number;
  attempts: QualificationAttempt[];
}

export interface ReplayTransition {
  mapId: string;
  wallId: string | null;
  point: Point2D;
  scoreDelta: number;
  validHit: boolean;
}

export interface RoundResult {
  round: number;
  winners: string[];
  losers: string[];
  leaderboard: Array<{
    agentId: string;
    score: number;
    completedWalls: number;
    segmentsTotal: number;
    invalidActions: number;
    qualificationPass: boolean;
  }>;
  qualification: QualificationResult[];
  episodes: WallEpisodeResult[];
}

export interface TournamentResult {
  createdAt: string;
  mode: QualificationMode;
  maps: string[];
  rounds: RoundResult[];
  finalWinnerIds: string[];
  winnersArtifact: Record<string, unknown>;
  losersArtifact: Record<string, unknown>;
}

