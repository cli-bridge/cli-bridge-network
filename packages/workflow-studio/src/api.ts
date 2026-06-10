import type { StudioConfig } from "./types";

export class StudioApi {
  constructor(private readonly config: StudioConfig) {}

  async health(): Promise<unknown> {
    return this.get("/health");
  }

  async workflows(): Promise<unknown> {
    return this.get("/workflows");
  }

  async workflow(path: string): Promise<unknown> {
    return this.get(`/workflows?path=${encodeURIComponent(path)}`);
  }

  async contract(path: string): Promise<unknown> {
    return this.get(`/messages/contract?workflow_path=${encodeURIComponent(path)}`);
  }

  async runWorkflow(): Promise<unknown> {
    return this.post("/workflows/run", {
      path: this.config.workflowPath,
      dry_run: this.config.dryRun,
      confirmed: this.config.confirmed,
    });
  }

  async killerDemo(): Promise<unknown> {
    return this.post("/demo/killer", {
      workflow_path: this.config.workflowPath,
      run: true,
      dry_run: this.config.dryRun,
      confirmed: this.config.confirmed,
      smoke_suite: true,
    });
  }

  async events(): Promise<unknown> {
    return this.get("/events?limit=30");
  }

  async audit(): Promise<unknown> {
    return this.get("/audit");
  }

  async artifacts(): Promise<unknown> {
    return this.get("/artifacts?limit=30");
  }

  private async get(path: string): Promise<unknown> {
    return this.request(path, { method: "GET" });
  }

  private async post(path: string, body: Record<string, unknown>): Promise<unknown> {
    return this.request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  private async request(path: string, init: RequestInit): Promise<unknown> {
    const headers = new Headers(init.headers);
    if (this.config.sessionToken.trim()) {
      headers.set("X-CBN-Session", this.config.sessionToken.trim());
    }
    const response = await fetch(`${this.config.daemonUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      headers,
    });
    const payload = await response.json().catch(() => ({ error: "invalid JSON response" }));
    if (!response.ok) {
      return { ok: false, status: response.status, payload };
    }
    return payload;
  }
}
