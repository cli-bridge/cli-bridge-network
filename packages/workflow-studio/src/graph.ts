import { LGraph, LGraphCanvas, LiteGraph } from "litegraph.js";
import type { AdapterAgentNodeBundle, WorkflowInspect } from "./types";

export interface StudioGraph {
  graph: LGraph;
  canvas: LGraphCanvas;
  render(workflow: WorkflowInspect | null, agentBundle?: AdapterAgentNodeBundle | null): void;
}

export function mountWorkflowGraph(canvas: HTMLCanvasElement): StudioGraph {
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
  const agentNodes = Array.isArray(agentBundle?.workflow_nodes) ? agentBundle.workflow_nodes : [];
  agentNodes.forEach((agentNode, index) => {
    const node = LiteGraph.createNode("basic/text");
    node.title = agentNode.id;
    node.pos = [40 + (index % 3) * 280, 300 + Math.floor(index / 3) * 150];
    node.size = [240, 94];
    node.properties = {
      text: `${agentNode.agent}\nuses=${agentNode.uses ?? "-"}\nagent node`,
    };
    graph.add(node);
  });
  graphCanvas.draw(true, true);
}
