import type { QuickstartRequest, StudioConfig } from "./types";

const REQUEST_TIMEOUT_MS = 15000;

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
    return this.networkGet("connect-package");
  }

  async networkQuickstart(): Promise<unknown> {
    return this.networkGet("quickstart");
  }

  async networkLaunchContract(): Promise<unknown> {
    return this.networkGet("launch-contract");
  }

  async networkEntryProfile(): Promise<unknown> {
    return this.networkGet("entry-profile");
  }

  async networkHarnessAgent(): Promise<unknown> {
    return this.networkGet("harness-agent");
  }

  async networkSdkBootstrap(): Promise<unknown> {
    return this.networkGet("sdk-bootstrap");
  }

  async networkConsumerManifest(): Promise<unknown> {
    return this.networkGet("consumer-manifest");
  }

  async networkAcceptance(): Promise<unknown> {
    return this.networkGet("acceptance");
  }

  async networkReadiness(): Promise<unknown> {
    return this.networkGet("readiness");
  }

  async importCatalog(): Promise<unknown> {
    return this.get("/imports/catalog");
  }

  async directCliReadiness(): Promise<unknown> {
    return this.get("/direct-cli/readiness");
  }

  async protocolWireConformance(): Promise<unknown> {
    const query = new URLSearchParams({
      target: "all",
      capability_id: "git.version",
    });
    return this.get(`/protocols/wire-conformance?${query.toString()}`);
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

  /**
   * Stream the real Workflow Agent loop (POST /adapter-agent/run, NDJSON).
   * Calls onEvent for each event (start/thinking/tool_call/tool_result/final/error/done).
   * Uses its own fetch with NO short timeout — the loop is long-running.
   */
  async runAgent(message: string, permission: string, onEvent: (event: Record<string, unknown>) => void): Promise<void> {
    const headers = new Headers({ "Content-Type": "application/json" });
    const token = this.sessionToken();
    if (token) headers.set("X-CBN-Session", token);
    let response: Response;
    try {
      response = await fetch(this.requestUrl("/adapter-agent/run"), {
        method: "POST",
        headers,
        body: JSON.stringify({ message, permission }),
      });
    } catch (err) {
      onEvent({ type: "error", error: `request failed: ${String(err)}` });
      return;
    }
    if (!response.ok || !response.body) {
      onEvent({ type: "error", error: `HTTP ${response.status}` });
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (line) {
          try {
            onEvent(JSON.parse(line));
          } catch {
            // skip non-JSON keepalive/partial lines
          }
        }
      }
    }
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

  private async networkGet(path: string): Promise<unknown> {
    return this.get(`/network/${path}?${this.networkQuery().toString()}`);
  }

  private networkQuery(): URLSearchParams {
    const query = new URLSearchParams({
      workflow_path: this.config.workflowPath,
      message: this.config.agentMessage,
      studio_url: this.studioOrigin,
    });
    const sessionToken = this.sessionToken();
    if (sessionToken) {
      query.set("session_token", sessionToken);
    }
    return query;
  }

  private sessionToken(): string {
    return this.config.sessionToken.trim();
  }

  private async request(path: string, init: RequestInit): Promise<unknown> {
    const result = await this.requestWithStatus(path, init);
    return result.payload;
  }

  private async requestWithStatus(pathOrUrl: string, init: RequestInit): Promise<{ http_status: number; payload: unknown }> {
    const headers = new Headers(init.headers);
    const sessionToken = this.sessionToken();
    if (sessionToken) {
      headers.set("X-CBN-Session", sessionToken);
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
