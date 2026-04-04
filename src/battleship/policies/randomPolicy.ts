import { SeededRng } from '@/battleship/rng';
import { BattleshipPolicy, Coord, PolicyContext } from '@/battleship/types';
import { unknownCells } from '@/battleship/policies/utils';

export const createRandomPolicy = (seed = 1337): BattleshipPolicy => {
  const rng = new SeededRng(seed);
  return {
    id: 'random',
    decide(ctx: PolicyContext) {
      const options = unknownCells(ctx);
      const shot: Coord =
        options[rng.nextInt(options.length)] ?? { x: 0, y: 0 };
      return {
        shot,
        confidence: 0.2,
        reason: 'random_unknown_cell',
      };
    },
  };
};

