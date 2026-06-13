import { LGraph, LGraphCanvas, LiteGraph } from "litegraph.js";
import type { AdapterAgentNodeBundle, WorkflowInspect, WorkflowTask } from "./types";

let studioTextNodeRegistered = false;

export interface StudioGraph {
  graph: LGraph;
  canvas: LGraphCanvas;
  render(workflow: WorkflowInspect | null, agentBundle?: AdapterAgentNodeBundle | null): void;
}

export function mountWorkflowGraph(canvas: HTMLCanvasElement): StudioGraph {
  ensureStudioTextNode();
  const graph = new LGraph();
  const graphCanvas = new LGraphCanvas(canvas, graph);
  graph.start();
  return {
    graph,
    canvas: graphCanvas,
    render(workflow: WorkflowInspect | null, agentBundle?: AdapterAgentNodeBundle | null) {
      renderWorkflow(graph, graphCanvas, workflow, agentBundle);
    },
  };
}

function renderWorkflow(
  graph: LGraph,
  graphCanvas: LGraphCanvas,
  workflow: WorkflowInspect | null,
  agentBundle?: AdapterAgentNodeBundle | null,
): void {
  graph.clear();
  const tasks = Array.isArray(workflow?.tasks) ? workflow.tasks : [];
  const taskNodes = new Map<string, any>();
  tasks.forEach((task, index) => {
    const node = createStudioTextNode();
    const risk = task.capability?.risk ?? "unknown";
    const selectors = selectorText(task);
    node.title = task.id;
    node.pos = [40 + (index % 3) * 280, 40 + Math.floor(index / 3) * 170];
    node.size = [250, selectors ? 122 : 104];
    node.properties = {
      text: `${task.uses}\nrisk=${risk}\nneeds=${(task.needs ?? []).join(",") || "-"}${selectors}`,
    };
    node.addInput?.("needs", "BridgeMessage");
    node.addOutput?.("message", "BridgeMessage");
    graph.add(node);
    taskNodes.set(task.id, node);
  });
  tasks.forEach((task) => {
    const consumer = taskNodes.get(task.id);
    if (!consumer) return;
    const dependencies = new Set([...(task.needs ?? []), ...(task.argsFrom ?? []).map((route) => route.task)]);
    dependencies.forEach((dependencyId) => {
      const producer = taskNodes.get(dependencyId);
      producer?.connect?.(0, consumer, 0);
    });
  });
  const agentNodes = Array.isArray(agentBundle?.workflow_nodes) ? agentBundle.workflow_nodes : [];
  agentNodes.forEach((agentNode, index) => {
    const node = createStudioTextNode();
    node.title = agentNode.id;
    node.pos = [40 + (index % 3) * 280, 300 + Math.floor(index / 3) * 150];
    node.size = [240, 94];
    node.properties = {
      text: `${agentNode.agent}\nuses=${agentNode.uses ?? "-"}\nagent node`,
    };
    node.addOutput?.("agent", "BridgeMessage");
    graph.add(node);
  });
  graphCanvas.draw(true, true);
}

function ensureStudioTextNode(): void {
  if (studioTextNodeRegistered) return;
  function StudioTextNode(this: any) {
    this.properties = { text: "" };
    this.size = [250, 104];
  }
  StudioTextNode.title = "CBN Text";
  StudioTextNode.prototype.onDrawForeground = function onDrawForeground(ctx: CanvasRenderingContext2D) {
    const lines = String(this.properties?.text ?? "").split("\n");
    ctx.fillStyle = "#dfe9da";
    ctx.font = "12px Consolas, monospace";
    lines.slice(0, 6).forEach((line, index) => {
      ctx.fillText(line, 10, 24 + index * 16);
    });
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

function selectorText(task: WorkflowTask): string {
  if (!Array.isArray(task.argsFrom) || task.argsFrom.length === 0) {
    return "";
  }
  const selectors = task.argsFrom
    .map((route) => `${route.task}:${route.selector}`)
    .join("\n");
  return `\nselectors=${selectors}`;
}
