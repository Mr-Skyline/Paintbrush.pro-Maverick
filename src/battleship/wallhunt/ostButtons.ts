import type { OstButtonTarget } from '@/battleship/wallhunt/types';

const STORAGE_KEY = 'wall-battleship-ost-buttons-v1';
const PROFILES_KEY = 'wall-battleship-ost-button-profiles-v1';
const ACTIVE_PROFILE_KEY = 'wall-battleship-ost-button-active-profile-v1';

export interface OstButtonProfile {
  name: string;
  buttons: OstButtonTarget[];
}

export const defaultOstButtons = (): OstButtonTarget[] => [
  { id: 'file_menu', label: 'File Menu', center: { x: 120, y: 22 }, tolerancePx: 6 },
  { id: 'open_btn', label: 'Open', center: { x: 188, y: 84 }, tolerancePx: 6 },
  { id: 'save_btn', label: 'Save', center: { x: 236, y: 84 }, tolerancePx: 6 },
  { id: 'boost_btn', label: 'Boost', center: { x: 402, y: 84 }, tolerancePx: 6 },
  { id: 'cond_list', label: 'Conditions List', center: { x: 1670, y: 312 }, tolerancePx: 6 },
  { id: 'page_prev', label: 'Prev Page', center: { x: 884, y: 86 }, tolerancePx: 6 },
  { id: 'page_next', label: 'Next Page', center: { x: 926, y: 86 }, tolerancePx: 6 },
  { id: 'status_bar', label: 'Status Bar', center: { x: 980, y: 1058 }, tolerancePx: 6 },
  { id: 'zoom_fit', label: 'Fit View', center: { x: 1040, y: 86 }, tolerancePx: 6 },
  { id: 'takeoff_canvas', label: 'Canvas Center', center: { x: 960, y: 540 }, tolerancePx: 6 },
];

export const loadOstButtons = (): OstButtonTarget[] => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultOstButtons();
    const parsed = JSON.parse(raw) as OstButtonTarget[];
    if (!Array.isArray(parsed) || parsed.length === 0) return defaultOstButtons();
    return parsed;
  } catch {
    return defaultOstButtons();
  }
};

export const saveOstButtons = (buttons: OstButtonTarget[]): void => {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(buttons));
};

export const resetOstButtons = (): OstButtonTarget[] => {
  const next = defaultOstButtons();
  saveOstButtons(next);
  return next;
};

const fallbackProfiles = (): OstButtonProfile[] => [
  {
    name: 'default',
    buttons: loadOstButtons(),
  },
];

export const loadOstButtonProfiles = (): OstButtonProfile[] => {
  try {
    const raw = window.localStorage.getItem(PROFILES_KEY);
    if (!raw) return fallbackProfiles();
    const parsed = JSON.parse(raw) as OstButtonProfile[];
    if (!Array.isArray(parsed) || parsed.length === 0) return fallbackProfiles();
    const normalized = parsed.filter(
      (p) => p && typeof p.name === 'string' && Array.isArray(p.buttons) && p.buttons.length > 0
    );
    return normalized.length > 0 ? normalized : fallbackProfiles();
  } catch {
    return fallbackProfiles();
  }
};

export const saveOstButtonProfiles = (profiles: OstButtonProfile[]): void => {
  window.localStorage.setItem(PROFILES_KEY, JSON.stringify(profiles));
};

export const loadActiveOstButtonProfileName = (): string => {
  const raw = window.localStorage.getItem(ACTIVE_PROFILE_KEY);
  if (!raw) return 'default';
  return raw;
};

export const saveActiveOstButtonProfileName = (name: string): void => {
  window.localStorage.setItem(ACTIVE_PROFILE_KEY, name);
};

