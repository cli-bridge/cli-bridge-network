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
  "Tail Events",
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

if (!html.includes("python -m cbn plugin preflight cli-anything")) {
  throw new Error("Dashboard does not expose the CLI-Anything preflight command.");
}

if (!html.includes("python -m cbn plugin market cli-anything list")) {
  throw new Error("Dashboard does not expose the CBN-managed CLI-Hub list command.");
}

if (!html.includes("python -m cbn plugin import-harness cli-anything gimp")) {
  throw new Error("Dashboard does not expose the CLI-Anything harness import command.");
}

if (!html.includes("python -m cbn plugin import-harness cli-anything gimp --from-market")) {
  throw new Error("Dashboard does not expose the CLI-Anything market metadata import command.");
}

if (!html.includes("python -m cbn plugin harness cli-anything status gimp --from-market")) {
  throw new Error("Dashboard does not expose the CLI-Anything harness status command.");
}

if (!html.includes("python -m cbn plugin harness cli-anything install gimp")) {
  throw new Error("Dashboard does not expose the managed CLI-Anything harness install command.");
}

if (!html.includes("python -m cbn event tail")) {
  throw new Error("Dashboard does not expose the event bus tail command.");
}

if (!html.includes("python -m cbn artifact list")) {
  throw new Error("Dashboard does not expose the runtime artifact list command.");
}

if (!html.includes("python -m cbn approvals list")) {
  throw new Error("Dashboard does not expose the approval queue list command.");
}

if (!html.includes("python -m cbn workflow run workflows/example.json --dry-run")) {
  throw new Error("Dashboard does not expose the runnable workflow dry-run command.");
}

if (!html.includes("python -m cbn parser list")) {
  throw new Error("Dashboard does not expose the parser registry list command.");
}

if (!html.includes("python -m cbn registry search")) {
  throw new Error("Dashboard does not expose the capability registry search command.");
}

if (!html.includes("python -m cbn protocol export all")) {
  throw new Error("Dashboard does not expose the protocol export command.");
}

if (!js.includes("stageCommand")) {
  throw new Error("Dashboard script does not stage commands.");
}

if (!css.includes(".control-grid")) {
  throw new Error("Dashboard stylesheet is missing the control grid.");
}

console.log("dashboard static check ok");
