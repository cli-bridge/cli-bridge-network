<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import {
  Activity,
  Boxes,
  Braces,
  FileJson,
  Gauge,
  History,
  Network,
  Play,
  RefreshCw,
  ShieldCheck,
  Wrench,
} from "lucide-vue-next";
import { StudioApi } from "./api";
import { mountWorkflowGraph, type StudioGraph } from "./graph";
import type { DockState, StudioConfig, WorkflowInspect, WorkflowTask } from "./types";

const config = reactive<StudioConfig>({
  daemonUrl: "http://127.0.0.1:8765",
  sessionToken: "",
  workflowPath: "workflows/cli-anything-macrocli-mermaid-routing.example.json",
  dryRun: true,
  confirmed: false,
});

const canvasRef = ref<HTMLCanvasElement | null>(null);
const graphRef = ref<StudioGraph | null>(null);
const workflow = ref<WorkflowInspect | null>(null);
const workflowList = ref<unknown>(null);
const contract = ref<unknown>(null);
const runResult = ref<unknown>(null);
const health = ref<unknown>(null);
const selectedTaskId = ref("");
const loading = ref("");
const error = ref("");
const dock = reactive<DockState>({ events: [], audit: [], artifacts: [] });

const api = computed(() => new StudioApi(config));
const tasks = computed<WorkflowTask[]>(() => (Array.isArray(workflow.value?.tasks) ? workflow.value.tasks : []));
const selectedTask = computed(() => tasks.value.find((task) => task.id === selectedTaskId.value) ?? tasks.value[0]);
const selectedRoutes = computed(() => selectedTask.value?.argsFrom ?? []);

async function call(label: string, fn: () => Promise<unknown>): Promise<unknown | null> {
  loading.value = label;
  error.value = "";
  try {
    return await fn();
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
    return null;
  } finally {
    loading.value = "";
  }
}

async function loadHealth() {
  health.value = await call("health", () => api.value.health());
}

async function loadWorkflows() {
  workflowList.value = await call("workflows", () => api.value.workflows());
}

async function inspectWorkflow() {
  const payload = await call("workflow", () => api.value.workflow(config.workflowPath));
  workflow.value = payload as WorkflowInspect;
  selectedTaskId.value = tasks.value[0]?.id ?? "";
  await nextTick();
  graphRef.value?.render(workflow.value);
}

async function inspectContract() {
  contract.value = await call("contract", () => api.value.contract(config.workflowPath));
}

async function runWorkflow() {
  runResult.value = await call("run", () => api.value.runWorkflow());
  await refreshEvidence();
}

async function refreshEvidence() {
  const [events, audit, artifacts] = await Promise.all([
    call("events", () => api.value.events()),
    call("audit", () => api.value.audit()),
    call("artifacts", () => api.value.artifacts()),
  ]);
  dock.events = Array.isArray(events) ? events : [];
  dock.audit = Array.isArray(audit) ? audit : [];
  dock.artifacts = Array.isArray(artifacts) ? artifacts : [];
}

async function loadAll() {
  await loadHealth();
  await loadWorkflows();
  await inspectWorkflow();
  await inspectContract();
  await refreshEvidence();
}

function pretty(payload: unknown): string {
  return JSON.stringify(payload ?? null, null, 2);
}

watch(
  () => config.workflowPath,
  () => {
    void inspectWorkflow();
    void inspectContract();
  },
);

onMounted(async () => {
  if (canvasRef.value) {
    graphRef.value = mountWorkflowGraph(canvasRef.value);
  }
  await loadAll();
});
</script>

<template>
  <main class="studio-shell">
    <aside class="left-rail">
      <header class="brand-block">
        <Network :size="22" />
        <div>
          <h1>CBN Workflow Studio</h1>
          <p>CLI-CLI workflow runtime</p>
        </div>
      </header>

      <label>
        Daemon URL
        <input v-model="config.daemonUrl" spellcheck="false" />
      </label>
      <label>
        Session token
        <input v-model="config.sessionToken" type="password" spellcheck="false" />
      </label>
      <label>
        Workflow path
        <textarea v-model="config.workflowPath" spellcheck="false" rows="3" />
      </label>

      <div class="switch-row">
        <label class="check"><input v-model="config.dryRun" type="checkbox" /> dry-run</label>
        <label class="check"><input v-model="config.confirmed" type="checkbox" /> confirmed</label>
      </div>

      <div class="command-grid">
        <button title="Load health, workflow, contract, evidence" @click="loadAll">
          <RefreshCw :size="16" /> Refresh
        </button>
        <button title="Run selected workflow through daemon" @click="runWorkflow">
          <Play :size="16" /> Run
        </button>
        <button title="Inspect workflow contract" @click="inspectContract">
          <ShieldCheck :size="16" /> Contract
        </button>
        <button title="Open maintainer console" onclick="window.open('../dashboard/src/index.html', '_blank')">
          <Wrench :size="16" /> Console
        </button>
      </div>

      <section class="status-panel">
        <div class="section-title"><Gauge :size="15" /> Health</div>
        <pre>{{ pretty(health) }}</pre>
      </section>
    </aside>

    <section class="graph-pane">
      <div class="toolbar">
        <div>
          <strong>{{ workflow?.workflow_id || "workflow" }}</strong>
          <span>{{ tasks.length }} tasks</span>
        </div>
        <span v-if="loading" class="pill">loading {{ loading }}</span>
        <span v-if="error" class="pill danger">{{ error }}</span>
      </div>
      <canvas ref="canvasRef" width="1100" height="640" />
    </section>

    <aside class="right-rail">
      <section>
        <div class="section-title"><Boxes :size="15" /> Task</div>
        <select v-model="selectedTaskId">
          <option v-for="task in tasks" :key="task.id" :value="task.id">{{ task.id }}</option>
        </select>
        <pre>{{ pretty(selectedTask) }}</pre>
      </section>
      <section>
        <div class="section-title"><Braces :size="15" /> Selectors</div>
        <pre>{{ pretty(selectedRoutes) }}</pre>
      </section>
      <section>
        <div class="section-title"><FileJson :size="15" /> Run result</div>
        <pre>{{ pretty(runResult) }}</pre>
      </section>
    </aside>

    <footer class="evidence-dock">
      <section>
        <div class="section-title"><Activity :size="15" /> Events</div>
        <pre>{{ pretty(dock.events) }}</pre>
      </section>
      <section>
        <div class="section-title"><History :size="15" /> Audit</div>
        <pre>{{ pretty(dock.audit) }}</pre>
      </section>
      <section>
        <div class="section-title"><FileJson :size="15" /> Artifacts</div>
        <pre>{{ pretty(dock.artifacts) }}</pre>
      </section>
    </footer>
  </main>
</template>
