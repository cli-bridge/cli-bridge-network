// Single source of truth for the persisted whiteboard layout: draggable card
// positions + the right Registry & Plugins dock position. One localStorage key
// replaces the previous scatter of per-surface keys.

const LAYOUT_KEY = "cbn.studio.layout";

interface Point {
  x: number;
  y: number;
}

interface LayoutState {
  rightDock?: Point;
  cards?: Record<string, Point>;
}

function read(): LayoutState {
  try {
    const raw = window.localStorage.getItem(LAYOUT_KEY);
    return raw ? (JSON.parse(raw) as LayoutState) : {};
  } catch {
    return {};
  }
}

function write(state: LayoutState): void {
  try {
    window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(state));
  } catch {
    // localStorage can be unavailable in restricted renderer contexts.
  }
}

export const layoutStore = {
  getCard(key: string): Point | null {
    return read().cards?.[key] ?? null;
  },
  setCard(key: string, point: Point): void {
    const state = read();
    state.cards = state.cards ?? {};
    state.cards[key] = point;
    write(state);
  },
  getRightDock(): Point | null {
    return read().rightDock ?? null;
  },
  setRightDock(point: Point): void {
    const state = read();
    state.rightDock = point;
    write(state);
  },
};
