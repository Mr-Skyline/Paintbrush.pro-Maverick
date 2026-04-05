import type {
  BoostReviewSummary,
  Condition,
  Phase,
  TakeoffTool,
  VoiceTurn,
} from '@/types';
import { normalizeConditionInput } from '@/utils/conditionStyle';
import { create } from 'zustand';

function nid() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
}

export interface SelectedMarkMeta {
  markType?: string;
  conditionIds?: string[];
  notes?: string;
  lengthFt?: number;
  areaSf?: number;
}

export interface AssemblyDef {
  id: string;
  name: string;
  heightFt: number;
  note: string;
}

export interface ProjectDocument {
  id: string;
  name: string;
  pageCount: number;
}

export interface BoostPrefs {
  defaultWallHeightFt: number;
  preferSplitCeilings: boolean;
  paintBothSidesInterior: boolean;
}

export interface ToolModes {
  continuousLinear: boolean;
  alignGrid: boolean;
  backoffArea: boolean;
}

const defaultBoostPrefs = (): BoostPrefs => ({
  defaultWallHeightFt: 8,
  preferSplitCeilings: true,
  paintBothSidesInterior: true,
});

const defaultToolModes = (): ToolModes => ({
  continuousLinear: false,
  alignGrid: false,
  backoffArea: false,
});

interface ProjectState {
  projectId: string | null;
  projectName: string;
  documents: ProjectDocument[];
  activeDocumentId: string | null;
  boostPrefs: BoostPrefs;
  toolModes: ToolModes;

  conditions: Condition[];
  selectedConditionIds: string[];
  phases: Phase[];
  activePhaseId: string | null;
  currentPage: number;
  totalPages: number;
  pixelsPerFoot: number;
  conditionSearch: string;
  tool: TakeoffTool;
  leftCollapsed: boolean;
  rightOpen: boolean;
  reviewOpen: boolean;
  boostReview: BoostReviewSummary | null;
  pageFabricJson: Record<string, unknown>;
  assemblies: AssemblyDef[];
  voiceLog: VoiceTurn[];
  voiceAlwaysListen: boolean;
  voiceListening: boolean;
  lastPdfFileName: string | null;
  highlightNid: string | null;
  selectedMarkNid: string | null;
  selectedMarkMeta: SelectedMarkMeta | null;

  /** Bumped when marks should be restyled from the condition table. */
  conditionRestyleToken: number;
  conditionRestyleRequest: null | {
    conditionIds: string[];
    scope: 'page' | 'selection';
    token: number;
  };

  /** Composite key docId:page0 for marks */
  fabricStorageKey: (pageIndex0: number) => string;

  setPdfMeta: (totalPages: number, fileName: string | null) => void;
  setPage: (p: number) => void;
  setPageFabricState: (pageIndex0: number, json: object) => void;
  getPageFabricState: (pageIndex0: number) => object | undefined;
  addCondition: (
    c: Partial<Omit<Condition, 'id'>> & Pick<Condition, 'name' | 'resultKind'>
  ) => string;
  updateCondition: (
    id: string,
    patch: Partial<Omit<Condition, 'id'>>,
    opts?: { applyToMarks?: 'none' | 'page' | 'selection' }
  ) => void;
  removeCondition: (id: string) => void;
  toggleSelectCondition: (id: string, multi: boolean) => void;
  setSelectedConditions: (ids: string[]) => void;
  setTool: (t: TakeoffTool) => void;
  setPixelsPerFoot: (n: number) => void;
  setConditionSearch: (s: string) => void;
  toggleLeft: () => void;
  toggleRight: () => void;
  setReviewOpen: (v: boolean) => void;
  setBoostReview: (r: BoostReviewSummary | null) => void;
  addAssembly: (a: Omit<AssemblyDef, 'id'>) => void;
  pushVoice: (turn: Omit<VoiceTurn, 'id' | 'at'>) => void;
  setVoiceListening: (v: boolean) => void;
  setVoiceAlwaysListen: (v: boolean) => void;
  setHighlightNid: (nid: string | null) => void;
  setSelectedMark: (nid: string | null, meta: SelectedMarkMeta | null) => void;
  applyBoostConditions: (suggested: Omit<Condition, 'id'>[]) => void;

  setProjectMeta: (projectId: string | null, projectName: string) => void;
  resetWorkspaceForNewProject: (projectName: string) => string;
  addPdfDocument: (docId: string, name: string, pageCount: number) => void;
  setActiveDocument: (docId: string) => void;
  updateDocumentPageCount: (docId: string, pageCount: number) => void;
  setBoostPrefs: (p: Partial<BoostPrefs>) => void;
  setToolModes: (p: Partial<ToolModes>) => void;
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projectId: null,
  projectName: '',
  documents: [],
  activeDocumentId: null,
  boostPrefs: defaultBoostPrefs(),
  toolModes: defaultToolModes(),

  conditions: [],
  selectedConditionIds: [],
  phases: [],
  activePhaseId: null,
  currentPage: 1,
  totalPages: 0,
  pixelsPerFoot: 48,
  conditionSearch: '',
  tool: 'select',
  leftCollapsed: true,
  rightOpen: false,
  reviewOpen: false,
  boostReview: null,
  pageFabricJson: {},
  assemblies: [],
  voiceLog: [],
  voiceAlwaysListen: false,
  voiceListening: false,
  lastPdfFileName: null,
  highlightNid: null,
  selectedMarkNid: null,
  selectedMarkMeta: null,

  conditionRestyleToken: 0,
  conditionRestyleRequest: null,

  fabricStorageKey: (pageIndex0) => {
    const doc = get().activeDocumentId ?? 'default';
    return `${doc}:${pageIndex0}`;
  },

  setPdfMeta: (totalPages, fileName) =>
    set({ totalPages, lastPdfFileName: fileName }),
  setPage: (p) => set({ currentPage: Math.max(1, p) }),
  setPageFabricState: (pageIndex0, json) =>
    set((s) => {
      const doc = s.activeDocumentId ?? 'default';
      const key = `${doc}:${pageIndex0}`;
      return {
        pageFabricJson: { ...s.pageFabricJson, [key]: json },
      };
    }),
  getPageFabricState: (pageIndex0) => {
    const s = get();
    const doc = s.activeDocumentId ?? 'default';
    const key = `${doc}:${pageIndex0}`;
    return s.pageFabricJson[key] as object | undefined;
  },

  addCondition: (c) => {
    const id = nid();
    const row = {
      ...normalizeConditionInput(c as Parameters<typeof normalizeConditionInput>[0]),
      id,
    };
    set((s) => ({
      conditions: [...s.conditions, row],
      selectedConditionIds: [id],
    }));
    return id;
  },
  updateCondition: (id, patch, opts) =>
    set((s) => {
      const cur = s.conditions.find((x) => x.id === id);
      if (!cur) return s;
      const merged = { ...cur, ...patch };
      const row = { ...normalizeConditionInput(merged), id };
      const next = s.conditions.map((c) => (c.id === id ? row : c));
      const apply = opts?.applyToMarks;
      if (apply === 'page' || apply === 'selection') {
        const token = s.conditionRestyleToken + 1;
        return {
          conditions: next,
          conditionRestyleToken: token,
          conditionRestyleRequest: {
            conditionIds: [id],
            scope: apply,
            token,
          },
        };
      }
      return { conditions: next };
    }),
  removeCondition: (id) =>
    set((s) => ({
      conditions: s.conditions.filter((x) => x.id !== id),
      selectedConditionIds: s.selectedConditionIds.filter((x) => x !== id),
    })),
  toggleSelectCondition: (id, multi) =>
    set((s) => {
      const has = s.selectedConditionIds.includes(id);
      if (!multi) return { selectedConditionIds: [id] };
      if (has) {
        const next = s.selectedConditionIds.filter((x) => x !== id);
        return { selectedConditionIds: next.length ? next : [id] };
      }
      return { selectedConditionIds: [...s.selectedConditionIds, id] };
    }),
  setSelectedConditions: (ids) => set({ selectedConditionIds: ids }),
  setTool: (tool) => set({ tool }),
  setPixelsPerFoot: (pixelsPerFoot) => set({ pixelsPerFoot }),
  setConditionSearch: (conditionSearch) => set({ conditionSearch }),
  toggleLeft: () => set((s) => ({ leftCollapsed: !s.leftCollapsed })),
  toggleRight: () => set((s) => ({ rightOpen: !s.rightOpen })),
  setReviewOpen: (reviewOpen) => set({ reviewOpen }),
  setBoostReview: (boostReview) =>
    set({ boostReview, reviewOpen: !!boostReview }),
  addAssembly: (a) =>
    set((s) => ({
      assemblies: [...s.assemblies, { ...a, id: nid() }],
    })),
  pushVoice: (turn) =>
    set((s) => ({
      voiceLog: [
        ...s.voiceLog,
        { ...turn, id: nid(), at: Date.now() },
      ].slice(-200),
    })),
  setVoiceListening: (voiceListening) => set({ voiceListening }),
  setVoiceAlwaysListen: (voiceAlwaysListen) => set({ voiceAlwaysListen }),
  setHighlightNid: (highlightNid) => set({ highlightNid }),
  setSelectedMark: (selectedMarkNid, selectedMarkMeta) =>
    set({ selectedMarkNid, selectedMarkMeta }),
  applyBoostConditions: (suggested) =>
    set((s) => {
      const newConds = suggested.map((c) => ({
        ...normalizeConditionInput(
          c as Parameters<typeof normalizeConditionInput>[0]
        ),
        id: nid(),
      }));
      return {
        conditions: [...s.conditions, ...newConds],
      };
    }),

  setProjectMeta: (projectId, projectName) => set({ projectId, projectName }),

  resetWorkspaceForNewProject: (projectName) => {
    const projectId = nid();
    set({
      projectId,
      projectName,
      documents: [],
      activeDocumentId: null,
      conditions: [],
      selectedConditionIds: [],
      phases: [],
      activePhaseId: null,
      currentPage: 1,
      totalPages: 0,
      pageFabricJson: {},
      assemblies: [],
      voiceLog: [],
      boostReview: null,
      reviewOpen: false,
      leftCollapsed: true,
      rightOpen: false,
      lastPdfFileName: null,
      selectedMarkNid: null,
      selectedMarkMeta: null,
      boostPrefs: defaultBoostPrefs(),
      toolModes: defaultToolModes(),
      conditionRestyleToken: 0,
      conditionRestyleRequest: null,
    });
    return projectId;
  },

  addPdfDocument: (docId, name, pageCount) =>
    set((s) => {
      const nextDocs = [...s.documents, { id: docId, name, pageCount }];
      const first = !s.activeDocumentId;
      return {
        documents: nextDocs,
        activeDocumentId: first ? docId : s.activeDocumentId,
        totalPages: first ? pageCount : s.totalPages,
        lastPdfFileName: first ? name : s.lastPdfFileName,
        currentPage: first ? 1 : s.currentPage,
      };
    }),

  setActiveDocument: (docId) =>
    set((s) => {
      const doc = s.documents.find((d) => d.id === docId);
      if (!doc) return s;
      return {
        activeDocumentId: docId,
        totalPages: doc.pageCount,
        lastPdfFileName: doc.name,
        currentPage: 1,
      };
    }),

  updateDocumentPageCount: (docId, pageCount) =>
    set((s) => {
      const documents = s.documents.map((d) =>
        d.id === docId ? { ...d, pageCount } : d
      );
      const active = documents.find((d) => d.id === s.activeDocumentId);
      return {
        documents,
        totalPages:
          active?.id === docId ? pageCount : s.totalPages,
      };
    }),

  setBoostPrefs: (p) =>
    set((s) => ({ boostPrefs: { ...s.boostPrefs, ...p } })),
  setToolModes: (p) =>
    set((s) => ({ toolModes: { ...s.toolModes, ...p } })),
}));
