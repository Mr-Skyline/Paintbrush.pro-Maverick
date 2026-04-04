import type { ReplayTransition } from '@/battleship/wallhunt/types';

export interface ReplayBuffers {
  positive: ReplayTransition[];
  negative: ReplayTransition[];
}

export const createReplayBuffers = (): ReplayBuffers => ({
  positive: [],
  negative: [],
});

export const appendTransition = (
  buffers: ReplayBuffers,
  row: ReplayTransition
): void => {
  if (row.scoreDelta > 0 && row.validHit) {
    buffers.positive.push(row);
    if (buffers.positive.length > 12000) {
      buffers.positive = buffers.positive.slice(-12000);
    }
  } else {
    buffers.negative.push(row);
    if (buffers.negative.length > 12000) {
      buffers.negative = buffers.negative.slice(-12000);
    }
  }
};

