declare module "litegraph.js" {
  export const LiteGraph: any;
  export class LGraph {
    clear(): void;
    add(node: any): void;
    remove(node: any): void;
    start(): void;
    stop(): void;
    [key: string]: any;
  }
  export class LGraphCanvas {
    constructor(canvas: HTMLCanvasElement, graph: LGraph);
    canvas: HTMLCanvasElement;
    ctx: CanvasRenderingContext2D | null;
    graph: LGraph;
    ds: any;
    draw(force?: boolean, forceBg?: boolean): void;
    drawNode(node: any, ctx: CanvasRenderingContext2D): void;
    resize(width?: number, height?: number): void;
    setDirty(fg?: boolean, bg?: boolean): void;
    static link_type_colors: Record<string, string>;
    // LiteGraph exposes many runtime properties; allow ad-hoc access during skinning.
    [key: string]: any;
  }
}
