import { create } from 'zustand';

type UIState = {
  /** Full drawer overlay (mobile + desktop expanded). */
  drawerOpen: boolean;
  setDrawer: (open: boolean) => void;
  toggleDrawer: () => void;
};

export const useUIStore = create<UIState>((set) => ({
  drawerOpen: false,
  setDrawer: (open) => set({ drawerOpen: open }),
  toggleDrawer: () => set((s) => ({ drawerOpen: !s.drawerOpen }))
}));
