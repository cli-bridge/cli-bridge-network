import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const html = readFileSync(join(root, "src", "index.html"), "utf8");
const js = readFileSync(join(root, "src", "app.js"), "utf8");
const css = readFileSync(join(root, "src", "styles.css"), "utf8");

const required = [
  "CLI-Anything",
  "Download / Clone",
  "Install",
  "Check Updates",
  "Update",
  "Approval Queue",
  "Artifact Bus",
  "Workflow DAG",
  "MCP",
  "A2A",
  "ACP",
];

const missing = required.filter((needle) => !html.includes(needle));
if (missing.length > 0) {
  throw new Error(`Dashboard is missing required labels: ${missing.join(", ")}`);
}

if (!html.includes("python -m cbn plugin plan cli-anything")) {
  throw new Error("Dashboard does not expose the CLI-Anything plan command.");
}

if (!js.includes("stageCommand")) {
  throw new Error("Dashboard script does not stage commands.");
}

if (!css.includes(".control-grid")) {
  throw new Error("Dashboard stylesheet is missing the control grid.");
}

console.log("dashboard static check ok");
