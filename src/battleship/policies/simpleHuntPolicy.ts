import { BattleshipPolicy, PolicyContext } from '@/battleship/types';
import { unresolvedHitClusters, unknownCells } from '@/battleship/policies/utils';

const coordKey = (x: number, y: number): string => `${x},${y}`;

export const createSimpleHuntPolicy = (): BattleshipPolicy => ({
  id: 'simple_hunt_target',
  decide(ctx: PolicyContext) {
    const unknownSet = new Set(unknownCells(ctx).map((c) => coordKey(c.x, c.y)));
    const clusters = unresolvedHitClusters(ctx);
    if (clusters.length > 0) {
      const c = clusters[0][0];
      const around = [
        { x: c.x + 1, y: c.y },
        { x: c.x - 1, y: c.y },
        { x: c.x, y: c.y + 1 },
        { x: c.x, y: c.y - 1 },
      ];
      const next = around.find((p) => unknownSet.has(coordKey(p.x, p.y)));
      if (next) {
        return { shot: next, confidence: 0.66, reason: 'simple_adjacent_hit_followup' };
      }
    }

    const parity = unknownCells(ctx).find((c) => (c.x + c.y) % 2 === 0);
    const shot = parity ?? unknownCells(ctx)[0] ?? { x: 0, y: 0 };
    return {
      shot,
      confidence: 0.45,
      reason: parity ? 'simple_parity_hunt' : 'simple_first_unknown',
    };
  },
});

