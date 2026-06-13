import { computed, onBeforeUnmount, reactive, ref, type ComputedRef, type Ref } from "vue";
import { layoutStore } from "./layoutStore";

// Reusable pointer-based drag for floating whiteboard cards.
//
// The card element must carry the `data-draggable-card` attribute and a drag
// handle (usually its header) must call `startDrag` on `pointerdown`. Positions
// are stored relative to `boundsEl` (the whiteboard surface). On the very first
// drag the card's rendered rect — which may be centered via a CSS transform —
// is converted into explicit left/top so the transform can be dropped.
//
// Mirrors the proven pattern already used by the right Registry & Plugins dock,
// generalised so multiple cards share one module-level z-counter for stacking.

export interface DraggableCardOptions {
  storageKey?: string;
  boundsEl: () => HTMLElement | null;
  cardEl: () => HTMLElement | null;
  enabled?: () => boolean;
  margin?: number;
}

export interface DraggableCard {
  position: { x: number; y: number };
  hasDragged: Ref<boolean>;
  dragging: Ref<boolean>;
  zIndex: Ref<number>;
  style: ComputedRef<Record<string, string>>;
  startDrag: (event: PointerEvent) => void;
  restore: () => void;
  reclamp: () => void;
  bringToFront: () => void;
}

// Shared stacking counter. Starts above the whiteboard canvas and base chrome
// so dragged cards always sit above static surfaces.
let draggableTopZ = 4;

export function useDraggableCard(options: DraggableCardOptions): DraggableCard {
  const margin = options.margin ?? 8;
  const position = reactive({ x: 0, y: 0 });
  const hasDragged = ref(false);
  const dragging = ref(false);
  const zIndex = ref(0);
  const grab = { x: 0, y: 0 };
  let activePointerId: number | null = null;

  const enabled = computed(() => (options.enabled ? options.enabled() : true));

  function clampPoint(x: number, y: number): { x: number; y: number } {
    const bounds = options.boundsEl();
    const card = options.cardEl();
    if (!bounds) return { x, y };
    const cardW = card?.offsetWidth ?? 0;
    const cardH = card?.offsetHeight ?? 0;
    const maxX = Math.max(margin, bounds.clientWidth - cardW - margin);
    const maxY = Math.max(margin, bounds.clientHeight - cardH - margin);
    return {
      x: Math.min(Math.max(margin, x), maxX),
      y: Math.min(Math.max(margin, y), maxY),
    };
  }

  function bringToFront(): void {
    draggableTopZ += 1;
    zIndex.value = draggableTopZ;
  }

  function restore(): void {
    if (!options.storageKey) return;
    const saved = layoutStore.getCard(options.storageKey);
    if (!saved) return;
    const clamped = clampPoint(saved.x, saved.y);
    position.x = clamped.x;
    position.y = clamped.y;
    hasDragged.value = true;
    bringToFront();
  }

  function persist(): void {
    if (!options.storageKey) return;
    layoutStore.setCard(options.storageKey, { x: position.x, y: position.y });
  }

  function startDrag(event: PointerEvent): void {
    if (event.button !== 0 || !enabled.value) return;
    const handle = event.currentTarget as HTMLElement | null;
    const card = handle?.closest("[data-draggable-card]") as HTMLElement | null;
    const bounds = options.boundsEl();
    if (!card || !bounds) return;
    const boundsRect = bounds.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    // Convert the rendered rect (which may use a CSS transform) into explicit
    // left/top so the transform can be removed for a stable drag origin.
    const snapped = clampPoint(cardRect.left - boundsRect.left, cardRect.top - boundsRect.top);
    position.x = snapped.x;
    position.y = snapped.y;
    hasDragged.value = true;
    grab.x = event.clientX - cardRect.left;
    grab.y = event.clientY - cardRect.top;
    dragging.value = true;
    activePointerId = event.pointerId;
    bringToFront();
    card.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }

  function onPointerMove(event: PointerEvent): void {
    if (!dragging.value || event.pointerId !== activePointerId) return;
    const bounds = options.boundsEl();
    if (!bounds) return;
    const boundsRect = bounds.getBoundingClientRect();
    const next = clampPoint(
      event.clientX - boundsRect.left - grab.x,
      event.clientY - boundsRect.top - grab.y,
    );
    position.x = next.x;
    position.y = next.y;
  }

  function endDrag(event?: PointerEvent): void {
    if (!dragging.value) return;
    if (event && event.pointerId !== activePointerId) return;
    dragging.value = false;
    activePointerId = null;
    persist();
  }

  function reclamp(): void {
    if (!hasDragged.value) return;
    const next = clampPoint(position.x, position.y);
    position.x = next.x;
    position.y = next.y;
    persist();
  }

  const style = computed<Record<string, string>>(() => {
    const next: Record<string, string> = {};
    if (enabled.value && hasDragged.value) {
      next.left = `${position.x}px`;
      next.top = `${position.y}px`;
      next.zIndex = String(zIndex.value || 4);
    }
    return next;
  });

  if (typeof window !== "undefined") {
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
  }

  onBeforeUnmount(() => {
    if (typeof window !== "undefined") {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", endDrag);
      window.removeEventListener("pointercancel", endDrag);
    }
  });

  return { position, hasDragged, dragging, zIndex, style, startDrag, restore, reclamp, bringToFront };
}
