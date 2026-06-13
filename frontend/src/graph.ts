import { LGraph, LGraphCanvas, LiteGraph } from "litegraph.js";
import type { AdapterAgentNodeBundle, WorkflowInspect, WorkflowTask } from "./types";

// Tone -> color. Keep in sync with styles.css :root tokens so LiteGraph nodes
// and the DOM glass cards share one design language.
const TONE = {
  blue: "#2f8dff",
  teal: "#27d6c0",
  green: "#4bd187",
  amber: "#f2b85b",
  violet: "#a875ff",
  danger: "#ff6b75",
} as const;

type Tone = keyof typeof TONE;

const RISK_TONE: Record<string, Tone> = {
  low: "blue",
  normal: "blue",
  medium: "teal",
  high: "amber",
  critical: "danger",
  unknown: "teal",
};

const NODE_BODY = "rgba(13,22,35,0.86)";
const NODE_TEXT = "#dfe9ff";
const NODE_MUTED = "#8fa1bb";

let studioTextNodeRegistered = false;
let linkColorsApplied = false;

export interface StudioGraph {
  graph: LGraph;
  canvas: LGraphCanvas;
  render(workflow: WorkflowInspect | null, agentBundle?: AdapterAgentNodeBundle | null): void;
  setZoom(scale: number): void;
  resetView(): void;
  dispose(): void;
}

export function mountWorkflowGraph(canvasEl: HTMLCanvasElement): StudioGraph {
  ensureStudioTextNode();
  applyLinkColors();

  const graph = new LGraph();
  const graphCanvas = new LGraphCanvas(canvasEl, graph);
  skinCanvas(graphCanvas);
  graphCanvas.resize();
  graph.start();
  graphCanvas.draw(true, true);

  const resizeObserver = new ResizeObserver(() => {
    graphCanvas.resize();
    graphCanvas.setDirty(true, true);
  });
  resizeObserver.observe(canvasEl);

  return {
    graph,
    canvas: graphCanvas,
    render(workflow, agentBundle) {
      renderWorkflow(graph, graphCanvas, workflow, agentBundle);
    },
    setZoom(scale) {
      zoomAt(graphCanvas, Math.min(2.5, Math.max(0.2, scale)));
    },
    resetView() {
      graphCanvas.ds.scale = 1;
      graphCanvas.ds.offset[0] = 0;
      graphCanvas.ds.offset[1] = 0;
      graphCanvas.setDirty(true, true);
    },
    dispose() {
      resizeObserver.disconnect();
      try {
        graph.stop();
      } catch {
        // graph may already be stopped
      }
    },
  };
}

// Transparent canvas: clear every frame (no smearing) but skip the opaque
// default fill and grid image so the CSS whiteboard background shows through.
function skinCanvas(graphCanvas: LGraphCanvas): void {
  graphCanvas.clear_background = true;
  graphCanvas.clear_background_color = null;
  graphCanvas.background_image = null;
  graphCanvas.default_link_color = TONE.blue;
  graphCanvas.node_title_color = NODE_TEXT;
  // Keep pan + node move + select; disable node search/create and context menus.
  graphCanvas.allow_searchbox = false;
  graphCanvas.allow_reconnect_links = false;
  graphCanvas.processContextMenu = () => {};
}

function applyLinkColors(): void {
  if (linkColorsApplied) return;
  const base = LGraphCanvas.link_type_colors || {};
  LGraphCanvas.link_type_colors = {
    ...base,
    BridgeMessage: TONE.teal,
    message: TONE.teal,
    agent: TONE.violet,
    number: TONE.blue,
    string: TONE.blue,
    default: TONE.blue,
  };
  linkColorsApplied = true;
}

function riskTone(risk?: string | null): Tone {
  const key = String(risk || "").toLowerCase();
  if (key in RISK_TONE) return RISK_TONE[key];
  if (/safe|verified|ready|^ok$|low/.test(key)) return "green";
  if (/high|danger|crit/.test(key)) return "danger";
  if (/warn|elev/.test(key)) return "amber";
  return "teal";
}

function renderWorkflow(
  graph: LGraph,
  graphCanvas: LGraphCanvas,
  workflow: WorkflowInspect | null,
  agentBundle?: AdapterAgentNodeBundle | null,
): void {
  graph.clear();
  const tasks = Array.isArray(workflow?.tasks) ? workflow.tasks : [];
  const layers = computeLayers(tasks);

  const columnWidth = 290;
  const rowHeight = 150;
  const startX = 56;
  const startY = 252;
  const byLayer: string[][] = [];
  for (const task of tasks) {
    const layer = layers.get(task.id) ?? 0;
    (byLayer[layer] ||= []).push(task.id);
  }
  const positions = new Map<string, [number, number]>();
  byLayer.forEach((ids, layer) => {
    ids.forEach((id, index) => {
      positions.set(id, [startX + layer * columnWidth, startY + index * rowHeight]);
    });
  });

  const taskNodes = new Map<string, any>();
  for (const task of tasks) {
    const node = createStudioTextNode();
    const tone = riskTone(task.capability?.risk);
    node.title = task.id;
    node.pos = positions.get(task.id) ?? [startX, startY];
    node.size = [244, 116];
    node.color = TONE[tone];
    node.bgcolor = NODE_BODY;
    node.properties = { text: nodeText(task), tone: TONE[tone] };
    node.addInput?.("needs", "BridgeMessage");
    node.addOutput?.("message", "BridgeMessage");
    graph.add(node);
    taskNodes.set(task.id, node);
  }

  for (const task of tasks) {
    const consumer = taskNodes.get(task.id);
    if (!consumer) continue;
    const deps = new Set<string>([
      ...(task.needs ?? []),
      ...(task.argsFrom ?? []).map((route) => route.task),
    ]);
    for (const depId of deps) {
      const producer = taskNodes.get(depId);
      producer?.connect?.(0, consumer, 0);
    }
  }

  const agentNodes = Array.isArray(agentBundle?.workflow_nodes) ? agentBundle.workflow_nodes : [];
  const agentLayer = byLayer.length;
  agentNodes.forEach((agentNode, index) => {
    const node = createStudioTextNode();
    node.title = agentNode.id;
    node.pos = [startX + agentLayer * columnWidth, startY + index * rowHeight];
    node.size = [240, 100];
    node.color = TONE.violet;
    node.bgcolor = NODE_BODY;
    node.properties = { text: `${agentNode.agent}\nuses=${agentNode.uses ?? "-"}`, tone: TONE.violet };
    node.addOutput?.("agent", "agent");
    graph.add(node);
  });

  graphCanvas.setDirty(true, true);
}

// Longest-path layering so the DAG reads left-to-right (ComfyUI style).
function computeLayers(tasks: WorkflowTask[]): Map<string, number> {
  const layer = new Map<string, number>();
  const byId = new Map<string, WorkflowTask>();
  for (const task of tasks) byId.set(task.id, task);
  const visiting = new Set<string>();
  const depth = (id: string): number => {
    const cached = layer.get(id);
    if (cached !== undefined) return cached;
    if (visiting.has(id)) return 0; // cycle guard
    visiting.add(id);
    const task = byId.get(id);
    const deps = task
      ? [...(task.needs ?? []), ...(task.argsFrom ?? []).map((route) => route.task)]
      : [];
    const d = deps.length ? Math.max(...deps.map(depth)) + 1 : 0;
    visiting.delete(id);
    layer.set(id, d);
    return d;
  };
  for (const task of tasks) depth(task.id);
  return layer;
}

function nodeText(task: WorkflowTask): string {
  const selectors = Array.isArray(task.argsFrom) && task.argsFrom.length
    ? task.argsFrom.map((route) => `${route.task}:${route.selector}`).join("  ")
    : "-";
  const needs = (task.needs ?? []).join(",") || "-";
  return `${task.uses}\nrisk=${task.capability?.risk ?? "unknown"} · needs=${needs}\nselect ${selectors}`;
}

function zoomAt(graphCanvas: LGraphCanvas, scale: number): void {
  const canvas = graphCanvas.canvas;
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;
  const oldScale = graphCanvas.ds.scale || 1;
  const worldX = (cx - graphCanvas.ds.offset[0]) / oldScale;
  const worldY = (cy - graphCanvas.ds.offset[1]) / oldScale;
  graphCanvas.ds.scale = scale;
  graphCanvas.ds.offset[0] = cx - worldX * scale;
  graphCanvas.ds.offset[1] = cy - worldY * scale;
  graphCanvas.setDirty(true, true);
}

// Word-aware wrap so long node text (e.g. the "select ..." route line) never
// overflows the node box. Any single unbreakable token wider than the box is
// ellipsised rather than clipped mid-glyph.
function wrapNodeText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const lines: string[] = [];
  for (const raw of text.split("\n")) {
    if (!raw) {
      lines.push("");
      continue;
    }
    let line = "";
    for (const part of raw.split(/(\s+)/)) {
      if (!line || ctx.measureText(line + part).width <= maxWidth) {
        line += part;
      } else {
        lines.push(line.trimEnd());
        line = part.replace(/^\s+/, "");
      }
    }
    if (line) lines.push(line);
  }
  return lines.map((line) => ellipsise(ctx, line, maxWidth));
}

function ellipsise(ctx: CanvasRenderingContext2D, line: string, maxWidth: number): string {
  if (ctx.measureText(line).width <= maxWidth) return line;
  let lo = 0;
  let hi = line.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (ctx.measureText(line.slice(0, mid) + "…").width <= maxWidth) lo = mid;
    else hi = mid - 1;
  }
  return line.slice(0, Math.max(1, lo)) + "…";
}

function ensureStudioTextNode(): void {
  if (studioTextNodeRegistered) return;
  function StudioTextNode(this: any) {
    this.properties = { text: "", tone: TONE.blue };
    this.size = [244, 116];
  }
  StudioTextNode.title = "CBN Task";
  StudioTextNode.prototype.onDrawForeground = function onDrawForeground(ctx: CanvasRenderingContext2D) {
    const text = String(this.properties?.text ?? "");
    const tone = String(this.properties?.tone ?? TONE.blue);
    const padX = 12;
    const lineH = 16;
    const top = 30;
    const maxLines = 8;
    ctx.font = "12px ui-monospace, Consolas, monospace";
    const maxWidth = Math.max(60, (this.size[0] || 244) - padX * 2);
    const wrapped = wrapNodeText(ctx, text, maxWidth).slice(0, maxLines);
    wrapped.forEach((line, index) => {
      ctx.fillStyle = index === 0 ? tone : index === 1 ? NODE_MUTED : NODE_TEXT;
      ctx.fillText(line, padX, top + index * lineH);
    });
    // Adapt node height to the wrapped body so text never spills past the box
    // (idempotent: stops writing once converged, so no per-frame re-layout churn).
    const needed = top + wrapped.length * lineH + 12;
    const cur = this.size[1] || 116;
    if (Math.abs(cur - needed) > 1) {
      this.size[1] = Math.min(260, Math.max(96, needed));
    }
  };
  LiteGraph.registerNodeType?.("cbn/text", StudioTextNode);
  studioTextNodeRegistered = true;
}

function createStudioTextNode(): any {
  const node = LiteGraph.createNode("cbn/text");
  if (!node) {
    throw new Error("LiteGraph cbn/text node registration failed");
  }
  return node;
}
