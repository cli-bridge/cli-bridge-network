declare module "litegraph.js" {
  export const LiteGraph: any;
  export class LGraph {
    clear(): void;
    add(node: any): void;
    start(): void;
    stop(): void;
  }
  export class LGraphCanvas {
    constructor(canvas: HTMLCanvasElement, graph: LGraph);
    draw(force?: boolean, forceBg?: boolean): void;
    resize(width?: number, height?: number): void;
  }
}
