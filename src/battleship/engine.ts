import { SeededRng } from '@/battleship/rng';
import {
  BOARD_SIZE,
  BattleshipGameState,
  CellState,
  Coord,
  DEFAULT_FLEET,
  PolicyContext,
  ShipPlacement,
  ShotResult,
} from '@/battleship/types';

const keyOf = (c: Coord): string => `${c.x},${c.y}`;

const inBounds = (c: Coord, size: number): boolean =>
  c.x >= 0 && c.y >= 0 && c.x < size && c.y < size;

const cloneCells = (cells: CellState[][]): CellState[][] =>
  cells.map((row) => row.slice());

const buildPublicBoard = (size: number): CellState[][] =>
  Array.from({ length: size }, () =>
    Array.from({ length: size }, () => 'unknown' as CellState)
  );

const cellsForPlacement = (
  origin: Coord,
  axis: 'horizontal' | 'vertical',
  length: number
): Coord[] =>
  Array.from({ length }, (_, idx) =>
    axis === 'horizontal'
      ? { x: origin.x + idx, y: origin.y }
      : { x: origin.x, y: origin.y + idx }
  );

const canPlaceShip = (
  occupied: Set<string>,
  origin: Coord,
  axis: 'horizontal' | 'vertical',
  length: number,
  size: number
): boolean => {
  const cells = cellsForPlacement(origin, axis, length);
  for (const c of cells) {
    if (!inBounds(c, size)) return false;
    if (occupied.has(keyOf(c))) return false;
  }
  return true;
};

const placeFleetRandom = (
  seed: number,
  size: number,
  lengths: readonly number[]
): ShipPlacement[] => {
  const rng = new SeededRng(seed);
  const occupied = new Set<string>();
  const placements: ShipPlacement[] = [];

  lengths.forEach((length, shipIdx) => {
    let placed = false;
    for (let attempt = 0; attempt < 500 && !placed; attempt += 1) {
      const axis = rng.next() < 0.5 ? 'horizontal' : 'vertical';
      const maxX = axis === 'horizontal' ? size - length : size - 1;
      const maxY = axis === 'vertical' ? size - length : size - 1;
      const origin = { x: rng.nextInt(maxX + 1), y: rng.nextInt(maxY + 1) };
      if (!canPlaceShip(occupied, origin, axis, length, size)) continue;
      const cells = cellsForPlacement(origin, axis, length);
      for (const c of cells) occupied.add(keyOf(c));
      placements.push({
        id: shipIdx + 1,
        length,
        origin,
        axis,
        cells,
      });
      placed = true;
    }
    if (!placed) {
      throw new Error(`Unable to place ship length=${length} seed=${seed}`);
    }
  });
  return placements;
};

const findShipByCell = (
  fleet: ShipPlacement[],
  coord: Coord
): ShipPlacement | null => {
  const coordKey = keyOf(coord);
  for (const ship of fleet) {
    if (ship.cells.some((c) => keyOf(c) === coordKey)) return ship;
  }
  return null;
};

const isShipSunk = (
  ship: ShipPlacement,
  shots: Set<string>
): boolean => ship.cells.every((c) => shots.has(keyOf(c)));

export const createGame = (opts?: {
  seed?: number;
  size?: number;
  fleetLengths?: readonly number[];
}): BattleshipGameState => {
  const size = opts?.size ?? BOARD_SIZE;
  const seed = opts?.seed ?? Date.now();
  const fleet = placeFleetRandom(seed, size, opts?.fleetLengths ?? DEFAULT_FLEET);
  const cells = buildPublicBoard(size);
  return {
    seed,
    size,
    fleet,
    shots: new Set<string>(),
    publicBoard: { size, cells },
    sunkShipIds: new Set<number>(),
    turn: 0,
    complete: false,
  };
};

export const listRemainingShips = (state: BattleshipGameState): number[] =>
  state.fleet
    .filter((s) => !state.sunkShipIds.has(s.id))
    .map((s) => s.length)
    .sort((a, b) => b - a);

export const buildPolicyContext = (
  state: BattleshipGameState,
  lastResult: ShotResult | null
): PolicyContext => ({
  board: {
    size: state.publicBoard.size,
    cells: cloneCells(state.publicBoard.cells),
  },
  remainingShips: listRemainingShips(state),
  turn: state.turn,
  lastResult,
});

export const applyShot = (
  state: BattleshipGameState,
  coord: Coord
): ShotResult => {
  if (!inBounds(coord, state.size)) {
    throw new Error(`Shot out of bounds: ${coord.x},${coord.y}`);
  }
  const coordKey = keyOf(coord);
  if (state.shots.has(coordKey)) {
    return {
      coord,
      kind: 'repeat',
      shipId: null,
      sunkShipLength: null,
      sunkCells: [],
    };
  }
  state.shots.add(coordKey);
  state.turn += 1;

  const ship = findShipByCell(state.fleet, coord);
  if (!ship) {
    state.publicBoard.cells[coord.y][coord.x] = 'miss';
    return {
      coord,
      kind: 'miss',
      shipId: null,
      sunkShipLength: null,
      sunkCells: [],
    };
  }

  state.publicBoard.cells[coord.y][coord.x] = 'hit';
  if (!isShipSunk(ship, state.shots)) {
    return {
      coord,
      kind: 'hit',
      shipId: ship.id,
      sunkShipLength: null,
      sunkCells: [],
    };
  }

  state.sunkShipIds.add(ship.id);
  for (const c of ship.cells) {
    state.publicBoard.cells[c.y][c.x] = 'sunk';
  }
  state.complete = state.sunkShipIds.size === state.fleet.length;
  return {
    coord,
    kind: 'sunk',
    shipId: ship.id,
    sunkShipLength: ship.length,
    sunkCells: ship.cells.slice(),
  };
};

export const allUnknownCells = (ctx: PolicyContext): Coord[] => {
  const out: Coord[] = [];
  for (let y = 0; y < ctx.board.size; y += 1) {
    for (let x = 0; x < ctx.board.size; x += 1) {
      if (ctx.board.cells[y][x] === 'unknown') out.push({ x, y });
    }
  }
  return out;
};

export const orthogonalNeighbors = (coord: Coord, size: number): Coord[] => {
  const raw: Coord[] = [
    { x: coord.x + 1, y: coord.y },
    { x: coord.x - 1, y: coord.y },
    { x: coord.x, y: coord.y + 1 },
    { x: coord.x, y: coord.y - 1 },
  ];
  return raw.filter((c) => inBounds(c, size));
};

export const unresolvedHitCells = (ctx: PolicyContext): Coord[] => {
  const out: Coord[] = [];
  for (let y = 0; y < ctx.board.size; y += 1) {
    for (let x = 0; x < ctx.board.size; x += 1) {
      if (ctx.board.cells[y][x] === 'hit') out.push({ x, y });
    }
  }
  return out;
};

