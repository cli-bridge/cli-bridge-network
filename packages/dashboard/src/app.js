const queue = document.getElementById("commandQueue");
const selectedCommand = document.getElementById("selectedCommand");
const operationLog = document.getElementById("operationLog");
const clearQueue = document.getElementById("clearQueue");
const copyCommand = document.getElementById("copyCommand");
const apiBase = document.getElementById("apiBase");
const apiStatus = document.getElementById("apiStatus");
const apiMode = document.getElementById("apiMode");
const apiResult = document.getElementById("apiResult");
const daemonToken = document.getElementById("daemonToken");
const saveDaemonToken = document.getElementById("saveDaemonToken");
const clearDaemonToken = document.getElementById("clearDaemonToken");
const daemonTokenStatus = document.getElementById("daemonTokenStatus");
const candidateSummary = document.getElementById("candidateSummary");
const clearCandidates = document.getElementById("clearCandidates");
const operationDetail = document.getElementById("operationDetail");
const clearOperationDetail = document.getElementById("clearOperationDetail");
const providerOperations = document.getElementById("providerOperations");
const clearProviderOperations = document.getElementById("clearProviderOperations");
const openAdapterAgentDialog = document.getElementById("openAdapterAgentDialog");
const adapterAgentDialog = document.getElementById("adapterAgentDialog");
const closeAdapterAgentDialog = document.getElementById("closeAdapterAgentDialog");
const adapterWorkflowPath = document.getElementById("adapterWorkflowPath");
const adapterAgentMessage = document.getElementById("adapterAgentMessage");
const adapterUseGlm = document.getElementById("adapterUseGlm");
const sendAdapterAgentTurn = document.getElementById("sendAdapterAgentTurn");
const stageAdapterAgentResume = document.getElementById("stageAdapterAgentResume");
const adapterAgentMessages = document.getElementById("adapterAgentMessages");
const adapterAgentToolLog = document.getElementById("adapterAgentToolLog");
const adapterAgentSetup = document.getElementById("adapterAgentSetup");
const adapterAgentRoutes = document.getElementById("adapterAgentRoutes");

const CBN_DAEMON_TOKEN_KEY = "cbn.daemonSessionToken";

let activeCommand = "";
let logLines = ["Dashboard loaded. Daemon API calls are available when cbn daemon is running."];
let adapterAgentLastTurn = null;

function renderLog() {
  operationLog.textContent = logLines.slice(-30).join("\n");
}

function appendLog(message) {
  const timestamp = new Date().toLocaleTimeString();
  logLines.push(`[${timestamp}] ${message}`);
  renderLog();
}

function renderJson(value) {
  return JSON.stringify(value, null, 2);
}

function displayPayload(path, payload) {
  if (path !== "/plugins/cli-anything/candidates" || !payload?.market) {
    return payload;
  }
  const market = {
    argv: payload.market.argv,
    exit_code: payload.market.exit_code,
    stdout_chars: payload.market.stdout_chars ?? String(payload.market.stdout || "").length,
    stderr_chars: payload.market.stderr_chars ?? String(payload.market.stderr || "").length,
    stdout_omitted: Boolean(payload.market.stdout || payload.market.stdout_omitted),
    parsed_json_omitted: Boolean(payload.market.parsed_json || payload.market.parsed_json_omitted),
    parsed_json_type: payload.market.parsed_json_type
      || (payload.market.parsed_json ? typeof payload.market.parsed_json : undefined),
    parsed_json_count: payload.market.parsed_json_count
      || (Array.isArray(payload.market.parsed_json) ? payload.market.parsed_json.length : undefined),
  };
  return { ...payload, market };
}

function requestBody(button) {
  const raw = button.dataset.apiBody;
  if (!raw) {
    return undefined;
  }
  return JSON.parse(raw);
}

function apiUrl(path) {
  const base = apiBase.value.replace(/\/+$/, "");
  return `${base}${path}`;
}

function storedDaemonToken() {
  return localStorage.getItem(CBN_DAEMON_TOKEN_KEY) || "";
}

function activeDaemonToken() {
  return daemonToken.value.trim() || storedDaemonToken();
}

function renderDaemonTokenStatus() {
  daemonTokenStatus.textContent = storedDaemonToken() ? "Token: saved" : "Token: not saved";
}

function daemonHeaders(hasBody) {
  const headers = {};
  if (hasBody) {
    headers["Content-Type"] = "application/json";
  }
  const token = activeDaemonToken();
  if (token) {
    headers["X-CBN-Session"] = token;
  }
  return headers;
}

function setApiStatus(label) {
  apiStatus.textContent = `API: ${label}`;
  apiMode.textContent = "Mode: API + Queue";
}

function candidateAction(label, command, apiPath, apiBody) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.dataset.command = command;
  button.dataset.apiMethod = "POST";
  button.dataset.apiPath = apiPath;
  button.dataset.apiBody = renderJson(apiBody);
  button.addEventListener("click", () => {
    stageCommand(command, label);
    callApi(button);
  });
  return button;
}

function renderCandidateSummary(payload) {
  candidateSummary.replaceChildren();
  if (!payload || payload.plugin_id !== "cli-anything") {
    candidateSummary.textContent = "No CLI-Anything candidate payload.";
    return;
  }

  const heading = document.createElement("div");
  heading.className = "candidate-stats";
  const stats = [
    `market ${payload.market_count ?? 0}`,
    `selected ${payload.selected_count ?? 0}`,
    `installable ${payload.install_candidate_count ?? 0}`,
    `blocked ${payload.blocked_count ?? 0}`,
  ];
  if (payload.with_probes) {
    stats.push(`probe ready ${payload.probe_ready_count ?? 0}`);
    stats.push(`probe blocked ${payload.probe_blocked_count ?? 0}`);
  }
  if (payload.market?.stdout_omitted) {
    stats.push(`stdout ${payload.market.stdout_chars ?? 0} chars omitted`);
  }
  heading.textContent = stats.join(" | ");
  candidateSummary.appendChild(heading);

  const rows = Array.isArray(payload.candidate_summary) && payload.candidate_summary.length > 0
    ? payload.candidate_summary
    : candidateSummaryFromCandidates(payload.candidates);
  if (rows.length === 0) {
    const empty = document.createElement("p");
    empty.textContent = "No candidates returned.";
    candidateSummary.appendChild(empty);
    return;
  }

  rows.forEach((row) => {
    const card = document.createElement("article");
    card.className = `candidate-card ${row.install_candidate ? "candidate-ok" : "candidate-blocked"}`;

    const title = document.createElement("h3");
    title.textContent = `#${row.rank ?? "-"} ${row.display_name || row.harness_name || "Unknown harness"}`;
    card.appendChild(title);

    const meta = document.createElement("p");
    meta.textContent = [
      row.capability_id,
      row.lifecycle_state,
      row.recommended_next_action,
    ].filter(Boolean).join(" | ");
    card.appendChild(meta);

    const badges = document.createElement("div");
    badges.className = "candidate-badges";
    [
      row.launch_ready ? "launch ready" : "not launch ready",
      row.manifest_imported ? "manifest imported" : "manifest missing",
      row.entrypoint_available ? "entrypoint ok" : "entrypoint missing",
      row.readiness_ready === true ? "probes ready" : null,
    ]
      .filter(Boolean)
      .forEach((label) => {
        const badge = document.createElement("span");
        badge.textContent = label;
        badges.appendChild(badge);
      });
    card.appendChild(badges);

    if (Array.isArray(row.blockers) && row.blockers.length > 0) {
      const blockers = document.createElement("ul");
      blockers.className = "candidate-blockers";
      row.blockers.forEach((blocker) => {
        const item = document.createElement("li");
        item.textContent = blocker;
        blockers.appendChild(item);
      });
      card.appendChild(blockers);
    }

    if (row.harness_name) {
      const actions = document.createElement("div");
      actions.className = "candidate-actions";
      actions.appendChild(
        candidateAction(
          "Evaluate",
          `python -m cbn plugin evaluate-harness cli-anything ${row.harness_name}`,
          "/plugins/cli-anything/evaluate-harness",
          { harness_name: row.harness_name, from_market: true },
        ),
      );
      actions.appendChild(
        candidateAction(
          "Prepare",
          `python -m cbn plugin prepare-harness cli-anything ${row.harness_name} --from-market`,
          "/plugins/cli-anything/prepare-harness",
          { harness_name: row.harness_name, from_market: true },
        ),
      );
      actions.appendChild(
        candidateAction(
          "Install Plan",
          `python -m cbn plugin harness cli-anything install ${row.harness_name}`,
          "/plugins/cli-anything/harness",
          { action: "install", harness_name: row.harness_name },
        ),
      );
      card.appendChild(actions);
    }

    candidateSummary.appendChild(card);
  });
}

function candidateSummaryFromCandidates(candidates) {
  if (!Array.isArray(candidates)) {
    return [];
  }
  return candidates.map((item) => {
    const lifecycle = item.lifecycle || {};
    const localStatus = item.local_status || {};
    const readiness = item.readiness || {};
    return {
      rank: item.rank,
      harness_name: item.harness_name,
      display_name: item.display_name,
      capability_id: item.capability_id,
      install_candidate: Boolean(item.install_candidate),
      recommended_next_action: item.recommended_next_action,
      lifecycle_state: lifecycle.state,
      blocker_count: Array.isArray(item.blockers) ? item.blockers.length : 0,
      blockers: Array.isArray(item.blockers) ? item.blockers : [],
      launch_ready: Boolean(localStatus.launch_ready),
      manifest_imported: Boolean(localStatus.manifest_imported),
      entrypoint_available: Boolean(localStatus.entrypoint_available),
      readiness_ready: readiness.ready,
      probe_blocker_count: readiness.probe_blocker_count,
    };
  });
}

function renderProviderOperations(payload) {
  providerOperations.replaceChildren();
  if (payload?.kind !== "PluginProviderOperationCatalog" || !Array.isArray(payload.operations)) {
    providerOperations.textContent = "No provider operation catalog loaded.";
    return;
  }

  const heading = document.createElement("div");
  heading.className = "candidate-stats";
  const summary = payload.summary || {};
  heading.textContent = [
    payload.plugin_id,
    `${summary.operation_count ?? payload.operations.length} operations`,
    `${summary.requires_confirmation_count ?? 0} confirm`,
    `${summary.write_or_execute_count ?? 0} side-effect`,
  ].filter(Boolean).join(" | ");
  providerOperations.appendChild(heading);

  payload.operations.forEach((operation) => {
    providerOperations.appendChild(providerOperationCard(payload, operation));
  });
}

function providerOperationCard(catalog, operation) {
  const card = document.createElement("article");
  card.className = `operation-card ${operation.requires_confirmation ? "operation-blocked" : "operation-ok"}`;

  const title = document.createElement("h3");
  title.textContent = `${operation.title || operation.id} (${operation.kind})`;
  card.appendChild(title);

  const meta = document.createElement("p");
  meta.textContent = operation.command || operation.api?.path || operation.id;
  card.appendChild(meta);

  const badges = document.createElement("div");
  badges.className = "candidate-badges";
  [
    operation.id,
    operation.has_required_inputs ? `${operation.input_count} inputs` : "no required inputs",
    operation.requires_confirmation ? "confirmation required" : "read only",
    operation.api?.method ? `${operation.api.method} ${operation.api.path}` : null,
  ]
    .filter(Boolean)
    .forEach((label) => {
      const badge = document.createElement("span");
      badge.textContent = label;
      badges.appendChild(badge);
    });
  card.appendChild(badges);

  const inputNames = providerOperationInputNames(operation);
  const form = document.createElement("div");
  form.className = "operation-form";
  inputNames.forEach((name) => {
    const label = document.createElement("label");
    label.textContent = name;
    const input = document.createElement("input");
    input.type = providerInputType(operation.input_schema?.[name]);
    input.placeholder = name;
    input.dataset.operationInput = name;
    label.appendChild(input);
    form.appendChild(label);
  });

  if (operation.requires_confirmation) {
    const label = document.createElement("label");
    label.className = "operation-checkbox";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.dataset.operationConfirm = "true";
    label.appendChild(input);
    label.append(" confirmed");
    form.appendChild(label);
  }

  const planButton = document.createElement("button");
  planButton.type = "button";
  planButton.textContent = "Plan";
  planButton.addEventListener("click", () => {
    const request = providerOperationPlanRequest(catalog.plugin_id, operation, card);
    planButton.dataset.command = request.command;
    planButton.dataset.apiMethod = "POST";
    planButton.dataset.apiPath = "/plugins/operation-plan";
    planButton.dataset.apiBody = renderJson(request.body);
    stageCommand(request.command, `Plan ${operation.id}`);
    callApi(planButton);
  });
  form.appendChild(planButton);
  card.appendChild(form);

  if (Array.isArray(operation.side_effects) && operation.side_effects.length > 0) {
    card.appendChild(listSection("Side Effects", operation.side_effects, "operation-list"));
  }

  return card;
}

function providerOperationInputNames(operation) {
  const names = new Set();
  if (Array.isArray(operation.required_inputs)) {
    operation.required_inputs.forEach((name) => names.add(name));
  }
  if (operation.input_schema && typeof operation.input_schema === "object" && !Array.isArray(operation.input_schema)) {
    Object.keys(operation.input_schema).forEach((name) => names.add(name));
  }
  return Array.from(names).sort();
}

function providerInputType(schemaValue) {
  if (schemaValue === "integer" || schemaValue === "number") {
    return "number";
  }
  if (schemaValue === "boolean") {
    return "checkbox";
  }
  return "text";
}

function providerOperationPlanRequest(pluginId, operation, card) {
  const inputs = {};
  card.querySelectorAll("[data-operation-input]").forEach((input) => {
    const name = input.dataset.operationInput;
    if (input.type === "checkbox") {
      inputs[name] = input.checked;
      return;
    }
    if (input.value.trim() !== "") {
      inputs[name] = input.value.trim();
    }
  });
  const confirmed = Boolean(card.querySelector("[data-operation-confirm]")?.checked);
  const inputFlags = Object.entries(inputs).map(([key, value]) => `--input ${key}=${commandInputValue(value)}`);
  return {
    command: [
      "python -m cbn plugin operation-plan",
      pluginId,
      operation.id,
      ...inputFlags,
      confirmed ? "--yes" : null,
    ].filter(Boolean).join(" "),
    body: {
      plugin_id: pluginId,
      operation_id: operation.id,
      inputs,
      confirmed,
    },
  };
}

function commandInputValue(value) {
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return String(value);
}

function renderOperationDetail(path, payload) {
  const isPluginOperationPath =
    path.startsWith("/plugins/cli-anything/") ||
    path.startsWith("/plugins/operations") ||
    path.startsWith("/plugins/operation-plan");
  if (!isPluginOperationPath || path === "/plugins/cli-anything/candidates") {
    return;
  }
  operationDetail.replaceChildren();
  const card = document.createElement("article");
  card.className = `operation-card ${operationBlockers(payload).length > 0 || payload?.ok === false ? "operation-blocked" : "operation-ok"}`;

  const title = document.createElement("h3");
  title.textContent = operationTitle(path, payload);
  card.appendChild(title);

  const summary = document.createElement("p");
  summary.textContent = operationSummary(payload);
  card.appendChild(summary);

  const badges = document.createElement("div");
  badges.className = "candidate-badges";
  operationBadges(payload).forEach((label) => {
    const badge = document.createElement("span");
    badge.textContent = label;
    badges.appendChild(badge);
  });
  card.appendChild(badges);

  const blockers = operationBlockers(payload);
  if (blockers.length > 0) {
    card.appendChild(listSection("Blockers", blockers, "candidate-blockers"));
  }

  const gates = operationGates(payload);
  if (gates.length > 0) {
    card.appendChild(listSection("Gates", gates, "operation-list"));
  }

  const commands = operationCommands(payload);
  if (commands.length > 0) {
    card.appendChild(listSection("Plan Commands", commands, "operation-list mono-list"));
  }

  operationDetail.appendChild(card);
}

function openAdapterAgent() {
  const command = "python -m cbn_adapter_agent --orchestrate --workflow-path workflows/auth-gated-first-run.example.json --glm-validate";
  stageCommand(command, "Open Adapter Agent");
  if (typeof adapterAgentDialog.showModal === "function") {
    adapterAgentDialog.showModal();
    return;
  }
  adapterAgentDialog.setAttribute("open", "");
}

function closeAdapterAgent() {
  if (typeof adapterAgentDialog.close === "function") {
    adapterAgentDialog.close();
    return;
  }
  adapterAgentDialog.removeAttribute("open");
}

async function sendAdapterAgent() {
  const workflowPath = adapterWorkflowPath.value.trim() || "workflows/auth-gated-first-run.example.json";
  const body = {
    workflow_path: workflowPath,
    message: adapterAgentMessage.value,
    use_glm: adapterUseGlm.checked,
  };
  const command = [
    "python -m cbn_adapter_agent --orchestrate",
    `--workflow-path ${workflowPath}`,
    adapterUseGlm.checked ? "--glm-validate" : null,
  ].filter(Boolean).join(" ");
  stageCommand(command, "Adapter Agent orchestration turn");
  adapterAgentMessages.textContent = "";
  appendAdapterAgentMessage("Running Adapter Agent orchestration...\n");
  appendLog("Calling Adapter Agent orchestration stream.");
  try {
    const response = await fetch(apiUrl("/adapter-agent/orchestrate-stream"), {
      method: "POST",
      headers: daemonHeaders(true),
      body: renderJson(body),
    });
    if (!response.body) {
      throw new Error("streaming response body is unavailable");
    }
    await readAdapterAgentStream(response);
    setApiStatus(response.ok ? "Connected" : `HTTP ${response.status}`);
    appendLog(`Adapter Agent stream: HTTP ${response.status}`);
  } catch (error) {
    setApiStatus("Unavailable");
    const fallback = {
      error: String(error),
      fallback_command: command,
    };
    apiResult.textContent = renderJson(fallback);
    adapterAgentMessages.textContent = renderJson(fallback);
    appendLog("Adapter Agent API unavailable; command remains staged.");
  }
}

async function readAdapterAgentStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    lines.filter(Boolean).forEach(handleAdapterAgentStreamEvent);
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    handleAdapterAgentStreamEvent(buffer);
  }
}

function handleAdapterAgentStreamEvent(line) {
  let event;
  try {
    event = JSON.parse(line);
  } catch {
    appendAdapterAgentMessage(`\n[stream parse error] ${line}`);
    return;
  }
  apiResult.textContent = renderJson(event);
  if (event.type === "plan" || event.type === "turn") {
    renderAdapterAgentTurn(event.payload);
    if (event.type === "turn") {
      adapterAgentMessages.textContent = event.payload?.assistant_message || adapterAgentMessages.textContent;
    }
    return;
  }
  if (event.type === "delta") {
    appendAdapterAgentMessage(event.text || "");
    return;
  }
  if (event.type === "fallback") {
    adapterAgentMessages.textContent = event.text || "";
    return;
  }
  if (event.type === "error") {
    appendAdapterAgentMessage(`\n[GLM error] ${event.error || "unknown error"}\n`);
    return;
  }
  if (event.type === "done") {
    appendLog(`Adapter Agent stream done; GLM accepted: ${Boolean(event.glm_content_accepted)}`);
  }
}

function appendAdapterAgentMessage(text) {
  adapterAgentMessages.textContent += text;
  adapterAgentMessages.scrollTop = adapterAgentMessages.scrollHeight;
}

function renderAdapterAgentTurn(payload) {
  if (payload?.kind !== "AdapterAgentOrchestrationTurn") {
    return;
  }
  adapterAgentLastTurn = payload;
  adapterAgentMessages.textContent = payload.assistant_message || renderJson(payload);
  renderAdapterAgentSetup(payload.auth_fallbacks || []);
  renderAdapterAgentRoutes(payload.cli_routes || []);
  const command = Array.isArray(payload.continuation?.command)
    ? payload.continuation.command.join(" ")
    : "";
  stageAdapterAgentResume.disabled = !command;
  stageAdapterAgentResume.dataset.command = command;
  stageAdapterAgentResume.dataset.label = `Resume ${payload.workflow_path}`;
}

function renderAdapterAgentSetup(fallbacks) {
  adapterAgentSetup.replaceChildren();
  if (!Array.isArray(fallbacks) || fallbacks.length === 0) {
    adapterAgentSetup.textContent = "No setup fallback required.";
    return;
  }
  fallbacks.forEach((fallback) => {
    const card = document.createElement("article");
    card.className = "operation-card operation-blocked";
    const title = document.createElement("h3");
    title.textContent = `${fallback.task_id}: ${fallback.uses}`;
    card.appendChild(title);

    const setup = fallback.setup || {};
    const summary = document.createElement("p");
    summary.textContent = [setup.title, fallback.status].filter(Boolean).join(" | ");
    card.appendChild(summary);

    if (Array.isArray(setup.user_steps) && setup.user_steps.length > 0) {
      card.appendChild(listSection("User Steps", setup.user_steps, "operation-list"));
    }
    if (Array.isArray(setup.verification_commands) && setup.verification_commands.length > 0) {
      const commandList = listSection(
        "Verification Commands",
        setup.verification_commands.map((command) => `${command.title || command.id}: ${command.argv.join(" ")}`),
        "operation-list mono-list",
      );
      card.appendChild(commandList);
      card.appendChild(setupToolActions(setup));
    }
    if (Array.isArray(fallback.missing_runtime_inputs) && fallback.missing_runtime_inputs.length > 0) {
      card.appendChild(
        listSection(
          "Missing Inputs",
          fallback.missing_runtime_inputs.map((input) => `${input.name}: ${input.kind}`),
          "candidate-blockers",
        ),
      );
    }
    adapterAgentSetup.appendChild(card);
  });
}

function setupToolActions(setup) {
  const wrapper = document.createElement("div");
  wrapper.className = "setup-tool-actions";
  (setup.verification_commands || []).forEach((command) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = setupCommandButtonLabel(command);
    button.title = command.argv.join(" ");
    button.addEventListener("click", () => {
      callAdapterAgentTool({
        action: "run-setup-tool",
        workflow_path: adapterWorkflowPath.value.trim() || "workflows/auth-gated-first-run.example.json",
        setup_id: setup.setup_id,
        command_id: command.id,
      });
    });
    wrapper.appendChild(button);
  });
  (setup.secret_inputs || [])
    .filter((secret) => secret.name === "OBSIDIAN_API_KEY")
    .forEach((secret) => {
      const label = document.createElement("label");
      label.textContent = secret.name;
      const input = document.createElement("input");
      input.type = "password";
      input.placeholder = "Paste key into this field only";
      label.appendChild(input);
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Save Session Secret";
      button.addEventListener("click", () => {
        callAdapterAgentTool({
          action: "store-secret",
          name: secret.name,
          value: input.value,
        });
        input.value = "";
      });
      wrapper.appendChild(label);
      wrapper.appendChild(button);
    });
  return wrapper;
}

function setupCommandButtonLabel(command) {
  if (command.id === "login" || command.id === "login-headless") {
    return command.id === "login-headless" ? "Start Headless Login" : "Start Login";
  }
  return command.title?.toLowerCase().includes("verify") ? command.title : `Verify ${command.title || command.id}`;
}

async function callAdapterAgentTool(body) {
  adapterAgentToolLog.textContent = "Running Adapter Agent tool use...";
  appendLog(`Adapter Agent tool use: ${body.action}`);
  try {
    const response = await fetch(apiUrl("/adapter-agent/tool-use"), {
      method: "POST",
      headers: daemonHeaders(true),
      body: renderJson(body),
    });
    const payload = await response.json();
    adapterAgentToolLog.textContent = renderJson(payload);
    apiResult.textContent = renderJson(payload);
    setApiStatus(response.ok ? "Connected" : `HTTP ${response.status}`);
    appendLog(`Adapter Agent tool use ${body.action}: HTTP ${response.status}`);
  } catch (error) {
    setApiStatus("Unavailable");
    adapterAgentToolLog.textContent = renderJson({ error: String(error), action: body.action });
    appendLog(`Adapter Agent tool use ${body.action}: API unavailable.`);
  }
}

function renderAdapterAgentRoutes(routes) {
  adapterAgentRoutes.replaceChildren();
  if (!Array.isArray(routes) || routes.length === 0) {
    adapterAgentRoutes.textContent = "No CLI routes returned.";
    return;
  }
  routes.forEach((route) => {
    const card = document.createElement("article");
    card.className = "operation-card operation-ok";
    const title = document.createElement("h3");
    title.textContent = `${route.task_id}: ${route.uses}`;
    card.appendChild(title);
    const summary = document.createElement("p");
    summary.textContent = route.communication || "direct CLI invocation";
    card.appendChild(summary);
    const details = [];
    if (Array.isArray(route.needs) && route.needs.length > 0) {
      details.push(`needs ${route.needs.join(", ")}`);
    }
    if (Array.isArray(route.args_from) && route.args_from.length > 0) {
      details.push(...route.args_from.map((item) => `${item.task} -> ${item.selector}`));
    }
    if (details.length > 0) {
      card.appendChild(listSection("Route", details, "operation-list mono-list"));
    }
    adapterAgentRoutes.appendChild(card);
  });
}

function operationTitle(path, payload) {
  const harness = payload?.harness_name ? `: ${payload.harness_name}` : "";
  if (path.endsWith("/evaluate-harness")) {
    return `Evaluation${harness}`;
  }
  if (path.endsWith("/prepare-harness")) {
    return `Preparation${harness}`;
  }
  if (path.endsWith("/harness")) {
    return payload?.action ? harnessActionTitle(payload.action) : `Harness Plan${harness}`;
  }
  return payload?.plugin_id ? `${payload.plugin_id}${harness}` : "Operation";
}

function harnessActionTitle(action) {
  const parts = String(action).split("-");
  if (parts.length >= 3 && parts[0] === "harness") {
    const verb = parts[1][0].toUpperCase() + parts[1].slice(1);
    return `Harness ${verb}: ${parts.slice(2).join("-")}`;
  }
  return `Harness ${action}`;
}

function operationSummary(payload) {
  const parts = [
    payload?.recommended_next_action ? `next ${payload.recommended_next_action}` : null,
    payload?.lifecycle?.state ? `state ${payload.lifecycle.state}` : null,
    payload?.install_candidate !== undefined ? `install candidate ${Boolean(payload.install_candidate)}` : null,
    payload?.ready_for_promotion !== undefined ? `promotion ready ${Boolean(payload.ready_for_promotion)}` : null,
    payload?.requires_confirmation !== undefined ? `confirmation ${Boolean(payload.requires_confirmation)}` : null,
  ];
  return parts.filter(Boolean).join(" | ") || "Operation response received.";
}

function operationBadges(payload) {
  const gates = payload?.gates || {};
  const badges = [];
  if (payload?.ok !== undefined) {
    badges.push(payload.ok ? "ok" : "not ok");
  }
  if (gates.manifest_valid !== undefined) {
    badges.push(gates.manifest_valid ? "manifest valid" : "manifest invalid");
  }
  if (gates.installed !== undefined) {
    badges.push(gates.installed ? "installed" : "not installed");
  }
  if (gates.launch_ready !== undefined) {
    badges.push(gates.launch_ready ? "launch ready" : "launch blocked");
  }
  if (payload?.commands) {
    badges.push(`${payload.commands.length} command plan`);
  }
  if (Array.isArray(payload?.missing_inputs) && payload.missing_inputs.length > 0) {
    badges.push(`${payload.missing_inputs.length} missing inputs`);
  }
  if (payload?.dispatch_ready !== undefined) {
    badges.push(payload.dispatch_ready ? "dispatch ready" : "dispatch blocked");
  }
  return badges;
}

function operationBlockers(payload) {
  if (Array.isArray(payload?.blockers)) {
    return payload.blockers;
  }
  if (Array.isArray(payload?.evaluation?.blockers)) {
    return payload.evaluation.blockers;
  }
  if (Array.isArray(payload?.promotion_blockers)) {
    return payload.promotion_blockers;
  }
  return [];
}

function operationGates(payload) {
  const gates = payload?.gates || payload?.evaluation?.gates || {};
  return Object.entries(gates).map(([key, value]) => `${key}: ${value}`);
}

function operationCommands(payload) {
  const commands = [];
  const planCommands = payload?.commands || payload?.plans?.install?.commands || payload?.plans?.launch?.commands;
  if (Array.isArray(planCommands)) {
    planCommands.forEach((command) => {
      if (Array.isArray(command.argv)) {
        commands.push(command.argv.join(" "));
      }
    });
  }
  if (Array.isArray(payload?.next_commands)) {
    commands.push(...payload.next_commands);
  }
  return commands;
}

function listSection(title, items, className) {
  const wrapper = document.createElement("div");
  wrapper.className = "operation-section";
  const heading = document.createElement("h4");
  heading.textContent = title;
  wrapper.appendChild(heading);
  const list = document.createElement("ul");
  list.className = className;
  items.forEach((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    list.appendChild(item);
  });
  wrapper.appendChild(list);
  return wrapper;
}

async function callApi(button) {
  const method = button.dataset.apiMethod || "GET";
  const path = button.dataset.apiPath;
  const label = button.textContent.trim();
  const confirmMessage = button.dataset.apiConfirm;
  if (confirmMessage && !window.confirm(confirmMessage)) {
    appendLog(`Cancelled API call: ${label}`);
    return;
  }

  const body = requestBody(button);
  const options = { method, headers: daemonHeaders(body !== undefined) };
  if (body !== undefined) {
    options.body = renderJson(body);
  }

  appendLog(`Calling API: ${method} ${path}`);
  try {
    const response = await fetch(apiUrl(path), options);
    const text = await response.text();
    let payload;
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = { raw: text };
    }
    apiResult.textContent = renderJson(displayPayload(path, payload));
    if (response.status === 403 && payload?.error === "session_denied") {
      appendLog(`${label}: daemon session token rejected.`);
    }
    if (path === "/plugins/cli-anything/candidates") {
      renderCandidateSummary(payload);
    }
    if (path.startsWith("/plugins/operations") && payload?.kind === "PluginProviderOperationCatalog") {
      renderProviderOperations(payload);
    }
    if (path === "/adapter-agent/orchestrate") {
      renderAdapterAgentTurn(payload);
    }
    renderOperationDetail(path, payload);
    setApiStatus(response.ok ? "Connected" : `HTTP ${response.status}`);
    appendLog(`${label}: HTTP ${response.status}`);
  } catch (error) {
    setApiStatus("Unavailable");
    apiResult.textContent = renderJson({ error: String(error), fallback_command: button.dataset.command });
    appendLog(`${label}: API unavailable; command remains staged.`);
  }
}

function stageCommand(command, label) {
  activeCommand = command;
  selectedCommand.textContent = command;

  const item = document.createElement("li");
  item.textContent = command;
  item.title = label;
  item.addEventListener("click", () => {
    activeCommand = command;
    selectedCommand.textContent = command;
    appendLog(`Selected queued command: ${label}`);
  });
  queue.appendChild(item);
  appendLog(`Staged: ${label}`);
}

document.querySelectorAll("button[data-command]").forEach((button) => {
  button.addEventListener("click", () => {
    stageCommand(button.dataset.command, button.textContent.trim());
    if (button.dataset.apiPath) {
      callApi(button);
    }
  });
});

clearQueue.addEventListener("click", () => {
  queue.innerHTML = "";
  activeCommand = "";
  selectedCommand.textContent = "Select any button to stage a command.";
  appendLog("Cleared command queue.");
});

clearCandidates.addEventListener("click", () => {
  candidateSummary.textContent = "Run Rank Candidates to inspect CLI-Anything market harnesses.";
  appendLog("Cleared candidate summary.");
});

clearProviderOperations.addEventListener("click", () => {
  providerOperations.textContent = "Run Provider Operations to render descriptor-driven plugin controls.";
  appendLog("Cleared provider operations.");
});

clearOperationDetail.addEventListener("click", () => {
  operationDetail.textContent = "Select a candidate action to inspect gates, blockers, and plans.";
  appendLog("Cleared operation detail.");
});

document.querySelectorAll("button[data-api-path]:not([data-command])").forEach((button) => {
  button.addEventListener("click", () => {
    callApi(button);
  });
});

document.getElementById("checkApi").addEventListener("click", () => {
  callApi({
    textContent: "Check API",
    dataset: {
      apiMethod: "GET",
      apiPath: "/health",
      command: "python -m cbn daemon serve --host 127.0.0.1 --port 8787",
    },
  });
});

openAdapterAgentDialog.addEventListener("click", openAdapterAgent);
closeAdapterAgentDialog.addEventListener("click", closeAdapterAgent);
sendAdapterAgentTurn.addEventListener("click", sendAdapterAgent);
stageAdapterAgentResume.addEventListener("click", () => {
  const command = stageAdapterAgentResume.dataset.command;
  if (!command) {
    appendLog("No Adapter Agent resume command available.");
    return;
  }
  stageCommand(command, stageAdapterAgentResume.dataset.label || "Adapter Agent resume");
});

daemonToken.value = storedDaemonToken();
renderDaemonTokenStatus();

saveDaemonToken.addEventListener("click", () => {
  const token = daemonToken.value.trim();
  if (!token) {
    localStorage.removeItem(CBN_DAEMON_TOKEN_KEY);
    renderDaemonTokenStatus();
    appendLog("Cleared daemon session token.");
    return;
  }
  localStorage.setItem(CBN_DAEMON_TOKEN_KEY, token);
  renderDaemonTokenStatus();
  appendLog("Saved daemon session token.");
});

clearDaemonToken.addEventListener("click", () => {
  daemonToken.value = "";
  localStorage.removeItem(CBN_DAEMON_TOKEN_KEY);
  renderDaemonTokenStatus();
  appendLog("Cleared daemon session token.");
});

renderLog();

copyCommand.addEventListener("click", async () => {
  if (!activeCommand) {
    appendLog("No selected command to copy.");
    return;
  }
  try {
    await navigator.clipboard.writeText(activeCommand);
    appendLog("Copied selected command.");
  } catch {
    appendLog("Clipboard API unavailable; command remains selected for manual copy.");
  }
});
