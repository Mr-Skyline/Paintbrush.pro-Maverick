import type {
  OstButtonTarget,
  Rect2D,
  UiClickableZone,
  WallInteractionConfig,
  WallInteractionPolicy,
  WallHuntMap,
} from '@/battleship/wallhunt/types';

const PROFILES_KEY = 'wall-battleship-training-profiles-v1';
const ACTIVE_KEY = 'wall-battleship-training-active-v1';
const TEMPLATES_KEY = 'wall-battleship-training-templates-v1';

export interface WallTrainingProfile {
  profileId: string;
  imageSignature: string;
  resolutionKey: string;
  interactionPolicy: WallInteractionPolicy;
  arenaRect: Rect2D;
  uiClickableZones: UiClickableZone[];
  buttonTargets: OstButtonTarget[];
  updatedAt: string;
}

const clampRect = (rect: Rect2D, map: WallHuntMap): Rect2D => {
  const x = Math.max(0, Math.min(map.width - 1, Math.round(rect.x)));
  const y = Math.max(0, Math.min(map.height - 1, Math.round(rect.y)));
  const maxW = Math.max(1, map.width - x);
  const maxH = Math.max(1, map.height - y);
  const width = Math.max(1, Math.min(maxW, Math.round(rect.width)));
  const height = Math.max(1, Math.min(maxH, Math.round(rect.height)));
  return { x, y, width, height };
};

export const resolutionKeyOf = (map: WallHuntMap): string => `${map.width}x${map.height}`;

export const imageSignatureOf = (map: WallHuntMap, label: string): string =>
  `${resolutionKeyOf(map)}:${String(label || map.mapId || 'unknown').trim().toLowerCase()}`;

export const defaultArenaRect = (map: WallHuntMap): Rect2D => ({
  x: Math.round(map.width * 0.2),
  y: Math.round(map.height * 0.08),
  width: Math.round(map.width * 0.62),
  height: Math.round(map.height * 0.88),
});

const parseProfiles = (): WallTrainingProfile[] => {
  try {
    const raw = window.localStorage.getItem(PROFILES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as WallTrainingProfile[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
};

const saveProfiles = (rows: WallTrainingProfile[]): void => {
  window.localStorage.setItem(PROFILES_KEY, JSON.stringify(rows));
};

const parseTemplates = (): Record<string, WallTrainingProfile> => {
  try {
    const raw = window.localStorage.getItem(TEMPLATES_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, WallTrainingProfile>;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

const saveTemplates = (rows: Record<string, WallTrainingProfile>): void => {
  window.localStorage.setItem(TEMPLATES_KEY, JSON.stringify(rows));
};

export const loadActiveTrainingProfileId = (): string => {
  const raw = window.localStorage.getItem(ACTIVE_KEY);
  return raw || '';
};

export const saveActiveTrainingProfileId = (profileId: string): void => {
  window.localStorage.setItem(ACTIVE_KEY, profileId);
};

export const toInteractionConfig = (
  profile: WallTrainingProfile
): WallInteractionConfig => ({
  arenaRect: profile.arenaRect,
  uiClickableZones: profile.uiClickableZones,
  buttonTargets: profile.buttonTargets,
  policy: profile.interactionPolicy,
});

export const ensureTrainingProfile = (opts: {
  map: WallHuntMap;
  imageLabel: string;
  fallbackButtons: OstButtonTarget[];
}): WallTrainingProfile => {
  const imageSignature = imageSignatureOf(opts.map, opts.imageLabel);
  const resolutionKey = resolutionKeyOf(opts.map);
  const profiles = parseProfiles();
  const existing = profiles.find((p) => p.imageSignature === imageSignature);
  if (existing) return existing;

  const templates = parseTemplates();
  const fromTemplate = templates[resolutionKey];
  if (fromTemplate) {
    const inherited: WallTrainingProfile = {
      ...fromTemplate,
      profileId: `profile-${Date.now()}`,
      imageSignature,
      resolutionKey,
      updatedAt: new Date().toISOString(),
    };
    saveProfiles([inherited, ...profiles]);
    return inherited;
  }

  const created: WallTrainingProfile = {
    profileId: `profile-${Date.now()}`,
    imageSignature,
    resolutionKey,
    interactionPolicy: 'buttons-only',
    arenaRect: defaultArenaRect(opts.map),
    uiClickableZones: [],
    buttonTargets: opts.fallbackButtons,
    updatedAt: new Date().toISOString(),
  };
  saveProfiles([created, ...profiles]);
  return created;
};

export const updateTrainingProfile = (
  profileId: string,
  patch: Partial<Omit<WallTrainingProfile, 'profileId' | 'imageSignature' | 'resolutionKey'>>
): WallTrainingProfile | null => {
  const profiles = parseProfiles();
  const idx = profiles.findIndex((p) => p.profileId === profileId);
  if (idx < 0) return null;
  const current = profiles[idx];
  const next: WallTrainingProfile = {
    ...current,
    ...patch,
    updatedAt: new Date().toISOString(),
  };
  profiles[idx] = next;
  saveProfiles(profiles);
  return next;
};

export const saveTrainingTemplateForResolution = (profile: WallTrainingProfile): void => {
  const templates = parseTemplates();
  templates[profile.resolutionKey] = profile;
  saveTemplates(templates);
};

export const withClampedProfile = (profile: WallTrainingProfile, map: WallHuntMap): WallTrainingProfile => ({
  ...profile,
  arenaRect: clampRect(profile.arenaRect, map),
  uiClickableZones: profile.uiClickableZones.map((z) => ({
    ...z,
    rect: clampRect(z.rect, map),
  })),
});
