export const BOARD_SIZE = 10;
export const DEFAULT_FLEET = [5, 4, 3, 3, 2] as const;

export type Axis = 'horizontal' | 'vertical';

export interface Coord {
  x: number;
  y: number;
}

export interface ShipPlacement {
  id: number;
  length: number;
  origin: Coord;
  axis: Axis;
  cells: Coord[];
}

export type CellState = 'unknown' | 'miss' | 'hit' | 'sunk';

export interface PublicBoard {
  size: number;
  cells: CellState[][];
}

export interface ShotResult {
  coord: Coord;
  kind: 'miss' | 'hit' | 'sunk' | 'repeat';
  shipId: number | null;
  sunkShipLength: number | null;
  sunkCells: Coord[];
}

export interface BattleshipGameState {
  seed: number;
  size: number;
  fleet: ShipPlacement[];
  shots: Set<string>;
  publicBoard: PublicBoard;
  sunkShipIds: Set<number>;
  turn: number;
  complete: boolean;
}

export interface PolicyContext {
  board: PublicBoard;
  remainingShips: number[];
  turn: number;
  lastResult: ShotResult | null;
}

export interface PolicyDecision {
  shot: Coord;
  confidence: number;
  reason: string;
  rankedCandidates?: Array<{
    coord: Coord;
    score: number;
    reason: string;
  }>;
}

export interface BattleshipPolicy {
  id: string;
  decide(ctx: PolicyContext): PolicyDecision;
  observeTransition?(
    prev: PolicyContext,
    decision: PolicyDecision,
    result: ShotResult,
    next: PolicyContext
  ): void;
}

export interface EpisodeSummary {
  policyId: string;
  seed: number;
  shots: number;
  hits: number;
  misses: number;
  sunkCount: number;
  complete: boolean;
  sinkTurns: number[];
  trace: Array<{
    turn: number;
    shot: Coord;
    result: ShotResult['kind'];
    confidence: number;
    reason: string;
  }>;
}

