const queue = document.getElementById("commandQueue");
const selectedCommand = document.getElementById("selectedCommand");
const operationLog = document.getElementById("operationLog");
const clearQueue = document.getElementById("clearQueue");
const copyCommand = document.getElementById("copyCommand");

let activeCommand = "";
let logLines = ["Dashboard loaded. Backend API is not connected."];

function renderLog() {
  operationLog.textContent = logLines.slice(-30).join("\n");
}

function appendLog(message) {
  const timestamp = new Date().toLocaleTimeString();
  logLines.push(`[${timestamp}] ${message}`);
  renderLog();
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
  });
});

clearQueue.addEventListener("click", () => {
  queue.innerHTML = "";
  activeCommand = "";
  selectedCommand.textContent = "Select any button to stage a command.";
  appendLog("Cleared command queue.");
});

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
