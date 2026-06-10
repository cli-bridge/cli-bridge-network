import { LGraph, LGraphCanvas, LiteGraph } from "litegraph.js";
import type { WorkflowInspect, WorkflowTask } from "./types";

export interface StudioGraph {
  graph: LGraph;
  canvas: LGraphCanvas;
  render(workflow: WorkflowInspect | null): void;
}

export function mountWorkflowGraph(canvas: HTMLCanvasElement): StudioGraph {
  const graph = new LGraph();
  const graphCanvas = new LGraphCanvas(canvas, graph);
  graph.start();
  return {
    graph,
    canvas: graphCanvas,
    render(workflow: WorkflowInspect | null) {
      renderWorkflow(graph, graphCanvas, workflow);
    },
  };
}

function renderWorkflow(graph: LGraph, graphCanvas: LGraphCanvas, workflow: WorkflowInspect | null): void {
  graph.clear();
  const tasks = Array.isArray(workflow?.tasks) ? workflow.tasks : [];
  tasks.forEach((task, index) => {
    const node = LiteGraph.createNode("basic/text");
    const risk = task.capability?.risk ?? "unknown";
    node.title = task.id;
    node.pos = [40 + (index % 3) * 280, 40 + Math.floor(index / 3) * 170];
    node.size = [240, 100];
    node.properties = {
      text: `${task.uses}\nrisk=${risk}\nneeds=${(task.needs ?? []).join(",") || "-"}`,
    };
    graph.add(node);
  });
  graphCanvas.draw(true, true);
}
