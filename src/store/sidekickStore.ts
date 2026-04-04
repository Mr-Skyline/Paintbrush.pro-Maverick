import type { CvTakeoffResult } from '@/lib/cvTypes';
import { create } from 'zustand';

export interface SidekickMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  at: number;
}

export interface SidekickScheduleEvent {
  id: string;
  title: string;
  startsAtIso: string;
  notes?: string;
}

interface SidekickState {
  uploadBusy: boolean;
  chatBusy: boolean;
  lastResult: CvTakeoffResult | null;
  messages: SidekickMessage[];
  schedule: SidekickScheduleEvent[];
  setUploadBusy: (busy: boolean) => void;
  setChatBusy: (busy: boolean) => void;
  setResult: (result: CvTakeoffResult | null) => void;
  pushMessage: (msg: Omit<SidekickMessage, 'id' | 'at'>) => void;
  addScheduleEvent: (evt: Omit<SidekickScheduleEvent, 'id'>) => void;
}

function id() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export const useSidekickStore = create<SidekickState>((set) => ({
  uploadBusy: false,
  chatBusy: false,
  lastResult: null,
  messages: [],
  schedule: [],
  setUploadBusy: (uploadBusy) => set({ uploadBusy }),
  setChatBusy: (chatBusy) => set({ chatBusy }),
  setResult: (lastResult) => set({ lastResult }),
  pushMessage: (msg) =>
    set((s) => ({
      messages: [...s.messages, { ...msg, id: id(), at: Date.now() }].slice(-150),
    })),
  addScheduleEvent: (evt) =>
    set((s) => ({
      schedule: [{ ...evt, id: id() }, ...s.schedule].slice(0, 50),
    })),
}));
