import type { OstProjectFileV1 } from '@/lib/ostTypes';
import { useProjectStore } from '@/store/projectStore';
import { migrateCondition } from '@/utils/conditionStyle';

export function buildOstProjectFile(): OstProjectFileV1 {
  const s = useProjectStore.getState();
  return {
    version: 1,
    projectId: s.projectId ?? '',
    projectName: s.projectName,
    updatedAt: Date.now(),
    conditions: s.conditions,
    phases: s.phases,
    assemblies: s.assemblies,
    pixelsPerFoot: s.pixelsPerFoot,
    currentPage: s.currentPage,
    documents: s.documents,
    activeDocumentId: s.activeDocumentId,
    pageFabricJson: s.pageFabricJson as Record<string, unknown>,
    voiceLog: s.voiceLog,
    selectedConditionIds: s.selectedConditionIds,
    boostPrefs: s.boostPrefs,
    toolModes: s.toolModes,
  };
}

export function applyOstProjectFile(data: OstProjectFileV1): void {
  useProjectStore.setState({
    projectId: data.projectId,
    projectName: data.projectName,
    conditions: (data.conditions ?? []).map(migrateCondition),
    phases: data.phases,
    assemblies: data.assemblies,
    pixelsPerFoot: data.pixelsPerFoot,
    currentPage: Math.max(1, data.currentPage),
    documents: data.documents,
    activeDocumentId: data.activeDocumentId,
    pageFabricJson: data.pageFabricJson as Record<string, unknown>,
    voiceLog: data.voiceLog ?? [],
    selectedConditionIds:
      data.selectedConditionIds?.length ? data.selectedConditionIds : [],
    boostPrefs: data.boostPrefs ?? {
      defaultWallHeightFt: 8,
      preferSplitCeilings: true,
      paintBothSidesInterior: true,
    },
    toolModes: data.toolModes ?? {
      continuousLinear: false,
      alignGrid: false,
      backoffArea: false,
    },
    totalPages: (() => {
      const active = data.documents.find(
        (d) => d.id === data.activeDocumentId
      );
      return (active ?? data.documents[0])?.pageCount ?? 0;
    })(),
    lastPdfFileName: (() => {
      const active = data.documents.find(
        (d) => d.id === data.activeDocumentId
      );
      return (active ?? data.documents[0])?.name ?? null;
    })(),
  });
}
