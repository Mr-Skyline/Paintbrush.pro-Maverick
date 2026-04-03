import type { AssemblyDef } from '@/store/projectStore';
import type { Condition, Phase, VoiceTurn } from '@/types';

/** Serialized `project.ost.json` (no PDF binaries — those live beside it or in IDB). */
export interface OstProjectFileV1 {
  version: 1;
  projectId: string;
  projectName: string;
  updatedAt: number;
  conditions: Condition[];
  phases: Phase[];
  assemblies: AssemblyDef[];
  pixelsPerFoot: number;
  currentPage: number;
  documents: { id: string; name: string; pageCount: number }[];
  activeDocumentId: string | null;
  pageFabricJson: Record<string, unknown>;
  voiceLog: VoiceTurn[];
  selectedConditionIds: string[];
  /** Boost / estimator prefs */
  boostPrefs?: {
    defaultWallHeightFt: number;
    preferSplitCeilings: boolean;
    paintBothSidesInterior: boolean;
  };
  toolModes?: {
    continuousLinear: boolean;
    alignGrid: boolean;
    backoffArea: boolean;
  };
}
