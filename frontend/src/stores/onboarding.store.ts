import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// Per-user "guided tour seen" flag. Mirrors the existing zustand + persist
// pattern from auth.store.ts (localStorage, `pfe-*` key) — no new mechanism.
// `seenUserIds` is the only persisted slice; `run` is transient UI state so
// the tour never auto-replays on reload.

type OnboardingState = {
  seenUserIds: string[];
  run: boolean;
  hasSeen: (userId: string) => boolean;
  markSeen: (userId: string) => void;
  startTour: () => void;
  stopTour: () => void;
};

export const useOnboardingStore = create<OnboardingState>()(
  persist(
    (set, get) => ({
      seenUserIds: [],
      run: false,
      hasSeen: (userId) => get().seenUserIds.includes(userId),
      markSeen: (userId) =>
        set((s) =>
          s.seenUserIds.includes(userId)
            ? s
            : { seenUserIds: [...s.seenUserIds, userId] }
        ),
      startTour: () => set({ run: true }),
      stopTour: () => set({ run: false }),
    }),
    {
      name: 'pfe-onboarding',
      partialize: (s) => ({ seenUserIds: s.seenUserIds }),
    }
  )
);
