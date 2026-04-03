import type { Condition, LinePattern, ResultKind } from '@/types';
import type { fabric } from 'fabric';

const PATTERNS: LinePattern[] = ['solid', 'dashed', 'dotted', 'dashdot'];

const RESULT_KINDS: ResultKind[] = [
  'linear',
  'area_gross',
  'area_net',
  'count',
  'assembly',
];

function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n));
}

export function hexAlpha(hex: string, a: number): string {
  const h = hex.replace('#', '');
  const n = parseInt(h, 16);
  if (!Number.isFinite(n) || h.length < 6) {
    return `rgba(148,163,184,${a})`;
  }
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r},${g},${b},${a})`;
}

export function linePatternToDashArray(
  pattern: LinePattern
): number[] | undefined {
  switch (pattern) {
    case 'solid':
      return undefined;
    case 'dashed':
      return [10, 6];
    case 'dotted':
      return [2, 5];
    case 'dashdot':
      return [12, 4, 2, 4];
    default:
      return undefined;
  }
}

export function isAreaResultKind(k: ResultKind): boolean {
  return k === 'area_gross' || k === 'area_net' || k === 'assembly';
}

export function primaryConditionForMark(
  conditionIds: string[] | undefined,
  conditions: Condition[]
): Condition | undefined {
  if (!conditionIds?.length) return undefined;
  const known = conditionIds.filter((id) =>
    conditions.some((c) => c.id === id)
  );
  if (!known.length) return undefined;
  return conditions.find((c) => c.id === known[0]);
}

/** Normalize user / Boost input into a full condition row (no `id`). */
export function normalizeConditionInput(
  c: Partial<Condition> & { strokeStyle?: 'solid' | 'dashed' }
): Omit<Condition, 'id'> {
  const linePattern: LinePattern =
    c.linePattern && PATTERNS.includes(c.linePattern)
      ? c.linePattern
      : c.strokeStyle === 'dashed'
        ? 'dashed'
        : 'solid';
  const strokeWidth =
    typeof c.strokeWidth === 'number'
      ? clamp(c.strokeWidth, 1, 24)
      : 2;
  const fillOpacity =
    typeof c.fillOpacity === 'number'
      ? clamp(c.fillOpacity, 0, 1)
      : 0.14;
  const name =
    typeof c.name === 'string' && c.name.trim() ? c.name.trim() : 'Condition';
  const color =
    typeof c.color === 'string' && /^#([0-9a-fA-F]{6})$/.test(c.color)
      ? c.color
      : '#64748b';
  const resultKind: ResultKind =
    c.resultKind && RESULT_KINDS.includes(c.resultKind)
      ? c.resultKind
      : 'linear';
  return {
    name,
    color,
    linePattern,
    strokeWidth,
    fillOpacity,
    resultKind,
    assemblyId: c.assemblyId,
    unitPrice: c.unitPrice,
  };
}

/** Upgrade persisted or legacy condition objects (e.g. `strokeStyle` only). */
export function migrateCondition(raw: unknown): Condition {
  const x = raw as Record<string, unknown>;
  const base = normalizeConditionInput({
    ...(x as object),
    strokeStyle: x.strokeStyle as 'solid' | 'dashed' | undefined,
  } as Partial<Condition>);
  const id =
    typeof x.id === 'string' && x.id.length > 0
      ? x.id
      : `c-${Date.now().toString(36)}`;
  return { ...base, id };
}

export function applyConditionVisualToFabricObject(
  obj: fabric.Object,
  conditionIds: string[],
  conditions: Condition[]
): void {
  const primary = primaryConditionForMark(conditionIds, conditions);
  if (!primary) return;
  const strokeDashArray = linePatternToDashArray(primary.linePattern);
  const fill = isAreaResultKind(primary.resultKind)
    ? hexAlpha(primary.color, primary.fillOpacity)
    : 'transparent';
  if (obj.type === 'circle') {
    obj.set({
      stroke: primary.color,
      strokeWidth: primary.strokeWidth,
      strokeDashArray,
      fill: hexAlpha(primary.color, 0.35),
    });
  } else {
    obj.set({
      stroke: primary.color,
      strokeWidth: primary.strokeWidth,
      strokeDashArray,
      fill,
    });
  }
}
