/** Mini LiteGraph preview for a workflow card.

Reuses the full graph renderer (graph.ts) on a small canvas so each card visually
IS its workflow (nodes connected left-to-right). The card workflow is a standard
WorkflowGraph JSON; its tasks are shaped close enough to WorkflowInspect tasks for
renderWorkflow to lay them out + link them.
*/

import { mountWorkflowGraph, type StudioGraph } from "./graph";

export interface MiniGraphHandle {
  dispose: () => void;
}

export function mountMiniGraph(
  canvasEl: HTMLCanvasElement | null,
  workflow: { spec?: { tasks?: unknown[] } } | null,
): MiniGraphHandle | null {
  if (!canvasEl) return null;
  let studio: StudioGraph | null = null;
  try {
    studio = mountWorkflowGraph(canvasEl);
    const tasks = (workflow?.spec?.tasks ?? []) as unknown[];
    // renderWorkflow expects a WorkflowInspect-shaped { tasks: [...] }
    studio.render({ tasks } as never, null);
    studio.setZoom(0.6);
  } catch {
    // a mini-graph failure must never break the card UI
    if (studio) studio.dispose();
    return null;
  }
  return { dispose: () => studio?.dispose() };
}
