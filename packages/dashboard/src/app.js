const queue = document.getElementById("commandQueue");
const selectedCommand = document.getElementById("selectedCommand");
const operationLog = document.getElementById("operationLog");
const clearQueue = document.getElementById("clearQueue");
const copyCommand = document.getElementById("copyCommand");
const apiBase = document.getElementById("apiBase");
const apiStatus = document.getElementById("apiStatus");
const apiMode = document.getElementById("apiMode");
const apiResult = document.getElementById("apiResult");

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
    apiResult.textContent = renderJson(payload);
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
