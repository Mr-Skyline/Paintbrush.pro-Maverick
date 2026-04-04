import { pointDistance } from '@/battleship/wallhunt/geometry';
import type {
  OstButtonTarget,
  QualificationMode,
  QualificationResult,
  WallHuntAgent,
} from '@/battleship/wallhunt/types';

const modeThreshold = (mode: QualificationMode): number =>
  mode === 'ranked' ? 10 : 7;

const stableNoise = (
  seedLike: string,
  amplitude: number
): { x: number; y: number } => {
  let h = 2166136261;
  for (let i = 0; i < seedLike.length; i += 1) {
    h ^= seedLike.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const u1 = ((h >>> 8) & 0xffff) / 65535;
  const u2 = ((h >>> 16) & 0xffff) / 65535;
  return {
    x: (u1 * 2 - 1) * amplitude,
    y: (u2 * 2 - 1) * amplitude,
  };
};

export const evaluateQualification = (opts: {
  agent: WallHuntAgent;
  buttons: OstButtonTarget[];
  mode: QualificationMode;
}): QualificationResult => {
  const precision = Math.max(0.2, opts.agent.weights.precision ?? 1.0);
  const clickSigma = Math.max(0, opts.agent.weights.clickSigma ?? 2.0);
  const minHitsRequired = modeThreshold(opts.mode);

  const attempts = opts.buttons.map((btn) => {
    const noiseAmp = clickSigma / precision;
    const noise = stableNoise(`${opts.agent.id}:${btn.id}`, noiseAmp);
    const predicted = {
      x: btn.center.x + noise.x,
      y: btn.center.y + noise.y,
    };
    const offsetPx = pointDistance(predicted, btn.center);
    const hit = offsetPx <= btn.tolerancePx;
    return {
      buttonId: btn.id,
      expected: btn.center,
      predicted,
      offsetPx,
      hit,
    };
  });

  const totalHits = attempts.filter((a) => a.hit).length;
  const meanOffsetPx =
    attempts.reduce((sum, a) => sum + a.offsetPx, 0) / Math.max(1, attempts.length);
  const maxOffsetPx = Math.max(...attempts.map((a) => a.offsetPx), 0);

  return {
    mode: opts.mode,
    agentId: opts.agent.id,
    pass: totalHits >= minHitsRequired,
    minHitsRequired,
    totalHits,
    meanOffsetPx,
    maxOffsetPx,
    attempts,
  };
};

