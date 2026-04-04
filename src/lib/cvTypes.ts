export interface CvWallLine {
  id: string;
  kind: 'exterior' | 'interior';
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  lf: number;
  confidence: number;
}

export interface CvRoomPolygon {
  id: string;
  label: string;
  points: Array<{ x: number; y: number }>;
  sf: number;
  confidence: number;
}

export interface CvCounts {
  doors: number;
  windows: number;
  fixtures: number;
}

export interface CvTakeoffResult {
  projectId: string;
  sourceName: string;
  page: number;
  confidence: number;
  scaleLabel: string;
  walls: CvWallLine[];
  rooms: CvRoomPolygon[];
  counts: CvCounts;
  quantities: {
    wallsLf: number;
    roomsSf: number;
  };
  annotatedImageUrl?: string;
  needsReview: boolean;
  auditId?: string;
}
