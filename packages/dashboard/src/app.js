const queue = document.getElementById("commandQueue");
const selectedCommand = document.getElementById("selectedCommand");
const operationLog = document.getElementById("operationLog");
const clearQueue = document.getElementById("clearQueue");
const copyCommand = document.getElementById("copyCommand");
const apiBase = document.getElementById("apiBase");
const apiStatus = document.getElementById("apiStatus");
const apiMode = document.getElementById("apiMode");
const apiResult = document.getElementById("apiResult");
const candidateSummary = document.getElementById("candidateSummary");
const clearCandidates = document.getElementById("clearCandidates");

let activeCommand = "";
let logLines = ["Dashboard loaded. Daemon API calls are available when cbn daemon is running."];

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

async function callApi(button) {
  const method = button.dataset.apiMethod || "GET";
  const path = button.dataset.apiPath;
  const label = button.textContent.trim();
  const confirmMessage = button.dataset.apiConfirm;
  if (confirmMessage && !window.confirm(confirmMessage)) {
    appendLog(`Cancelled API call: ${label}`);
    return;
  }

  const options = { method, headers: { "Content-Type": "application/json" } };
  const body = requestBody(button);
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
    if (path === "/plugins/cli-anything/candidates") {
      renderCandidateSummary(payload);
    }
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
