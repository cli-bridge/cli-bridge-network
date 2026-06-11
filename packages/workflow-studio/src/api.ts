import type { QuickstartRequest, StudioConfig } from "./types";

const REQUEST_TIMEOUT_MS = 8000;

export class StudioApi {
  constructor(
    private readonly config: StudioConfig,
    private readonly studioOrigin: string = window.location.origin,
  ) {}

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

  async adapterAgentNodeBundle(): Promise<unknown> {
    const query = new URLSearchParams({
      workflow_path: this.config.workflowPath,
      message: this.config.agentMessage,
    });
    return this.get(`/adapter-agent/node-bundle?${query.toString()}`);
  }

  async workflowRequestPlan(): Promise<unknown> {
    return this.post("/adapter-agent/workflow-request-plan", {
      workflow_path: this.config.workflowPath,
      message: this.config.agentMessage,
      dry_run: this.config.dryRun,
      confirmed: this.config.confirmed,
    });
  }

  async toolCallPlan(): Promise<unknown> {
    return this.post("/adapter-agent/tool-call-plan", {
      workflow_path: this.config.workflowPath,
      message: this.config.agentMessage,
    });
  }

  async networkConnectPackage(): Promise<unknown> {
    const query = new URLSearchParams({
      workflow_path: this.config.workflowPath,
      message: this.config.agentMessage,
      studio_url: this.studioOrigin,
    });
    if (this.config.sessionToken.trim()) {
      query.set("session_token", this.config.sessionToken.trim());
    }
    return this.get(`/network/connect-package?${query.toString()}`);
  }

  async networkLaunchContract(): Promise<unknown> {
    const query = new URLSearchParams({
      workflow_path: this.config.workflowPath,
      message: this.config.agentMessage,
      studio_url: this.studioOrigin,
    });
    if (this.config.sessionToken.trim()) {
      query.set("session_token", this.config.sessionToken.trim());
    }
    return this.get(`/network/launch-contract?${query.toString()}`);
  }

  async networkEntryProfile(): Promise<unknown> {
    const query = new URLSearchParams({
      workflow_path: this.config.workflowPath,
      message: this.config.agentMessage,
      studio_url: this.studioOrigin,
    });
    if (this.config.sessionToken.trim()) {
      query.set("session_token", this.config.sessionToken.trim());
    }
    return this.get(`/network/entry-profile?${query.toString()}`);
  }

  async networkAcceptance(): Promise<unknown> {
    const query = new URLSearchParams({
      workflow_path: this.config.workflowPath,
      message: this.config.agentMessage,
      studio_url: this.studioOrigin,
    });
    if (this.config.sessionToken.trim()) {
      query.set("session_token", this.config.sessionToken.trim());
    }
    return this.get(`/network/acceptance?${query.toString()}`);
  }

  async networkReadiness(): Promise<unknown> {
    const query = new URLSearchParams({
      workflow_path: this.config.workflowPath,
      message: this.config.agentMessage,
      studio_url: this.studioOrigin,
    });
    if (this.config.sessionToken.trim()) {
      query.set("session_token", this.config.sessionToken.trim());
    }
    return this.get(`/network/readiness?${query.toString()}`);
  }

  async importCatalog(): Promise<unknown> {
    return this.get("/imports/catalog");
  }

  async networkVerify(): Promise<unknown> {
    return this.post("/network/verify", {
      workflow_path: this.config.workflowPath,
      studio_url: this.studioOrigin,
      message: this.config.agentMessage,
      timeout_seconds: 8,
    });
  }

  async quickstartRequest(request: QuickstartRequest): Promise<{ http_status: number; payload: unknown }> {
    const method = request.method || "GET";
    const headers = new Headers(request.headers);
    const init: RequestInit = { method, headers };
    if (request.json) {
      headers.set("Content-Type", "application/json");
      init.body = JSON.stringify(request.json);
    }
    return this.requestWithStatus(request.url || "", init);
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
    const result = await this.requestWithStatus(path, init);
    return result.payload;
  }

  private async requestWithStatus(pathOrUrl: string, init: RequestInit): Promise<{ http_status: number; payload: unknown }> {
    const headers = new Headers(init.headers);
    if (this.config.sessionToken.trim()) {
      headers.set("X-CBN-Session", this.config.sessionToken.trim());
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(this.requestUrl(pathOrUrl), {
        ...init,
        headers,
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => ({ error: "invalid JSON response" }));
      if (!response.ok) {
        return { http_status: response.status, payload: { ok: false, status: response.status, payload } };
      }
      return { http_status: response.status, payload };
    } finally {
      window.clearTimeout(timeout);
    }
  }

  private requestUrl(pathOrUrl: string): string {
    if (/^https?:\/\//i.test(pathOrUrl)) {
      return pathOrUrl;
    }
    return `${this.config.daemonUrl.replace(/\/$/, "")}${pathOrUrl}`;
  }
}
