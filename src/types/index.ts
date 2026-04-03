export type ResultKind = 'linear' | 'area_gross' | 'area_net' | 'count' | 'assembly';

export type LinePattern = 'solid' | 'dashed' | 'dotted' | 'dashdot';

export type TakeoffTool =
  | 'select'
  | 'pan'
  | 'line'
  | 'polyline'
  | 'polygon'
  | 'arc'
  | 'count'
  | 'measure'
  | 'text'
  /** Drag a rectangle: tells Grok / voice which part of the sheet to focus on */
  | 'ai_scope';

export interface Condition {
  id: string;
  name: string;
  color: string;
  /** Outline pattern (OST-style line style). */
  linePattern: LinePattern;
  /** Stroke width in logical px on the overlay canvas. */
  strokeWidth: number;
  /** Polygon / assembly fill alpha (0–1) when result is area or assembly. */
  fillOpacity: number;
  resultKind: ResultKind;
  assemblyId?: string;
  unitPrice?: number;
}

export interface Phase {
  id: string;
  name: string;
  pageIndices: number[];
}

export interface TextItem {
  str: string;
  x: number;
  y: number;
  width: number;
  height: number;
  pageIndex: number;
}

export interface BoostFinding {
  id: string;
  kind: 'wall' | 'ceiling_act' | 'ceiling_gwb' | 'door' | 'window' | 'room' | 'fixture';
  description: string;
  conditionName: string;
  geometry: BoostGeometry;
  confidence: number;
}

export type BoostGeometry =
  | { type: 'line'; x1: number; y1: number; x2: number; y2: number }
  | { type: 'polygon'; points: { x: number; y: number }[] }
  | { type: 'rect'; x: number; y: number; w: number; h: number }
  | { type: 'point'; x: number; y: number };

export interface BoostReviewSummary {
  headline: string;
  findings: BoostFinding[];
  stats: {
    wallLf?: number;
    doors?: number;
    windows?: number;
    ceilingActSf?: number;
    ceilingGwbSf?: number;
    rooms?: number;
  };
  suggestedConditions: Omit<Condition, 'id'>[];
}

export interface VoiceTurn {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  at: number;
}

export interface ProjectSnapshot {
  conditions: Condition[];
  phases: Phase[];
  pixelsPerFoot: number;
  conditionSearch: string;
}
