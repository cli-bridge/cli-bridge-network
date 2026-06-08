import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const html = readFileSync(join(root, "src", "index.html"), "utf8");
const js = readFileSync(join(root, "src", "app.js"), "utf8");
const css = readFileSync(join(root, "src", "styles.css"), "utf8");
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));

const required = [
  "CLI-Anything",
  "Download / Clone",
  "Install",
  "Check Updates",
  "Update",
  "Daemon API",
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

if (!html.includes('data-api-path="/plugins/cli-anything/preflight"')) {
  throw new Error("Dashboard does not wire CLI-Anything preflight to the daemon API.");
}

if (!html.includes('data-api-path="/plugins/execute"')) {
  throw new Error("Dashboard does not wire plugin execution to the daemon API.");
}

if (!html.includes("python -m cbn plugin market cli-anything list")) {
  throw new Error("Dashboard does not expose the CBN-managed CLI-Hub list command.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/market"')) {
  throw new Error("Dashboard does not wire CLI-Hub market calls to the daemon API.");
}

if (!html.includes("python -m cbn plugin sync-market cli-anything --query image --limit 20")) {
  throw new Error("Dashboard does not expose the CLI-Anything market sync preview command.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/sync-market"')) {
  throw new Error("Dashboard does not wire CLI-Anything market sync to the daemon API.");
}

if (!html.includes("python -m cbn plugin import-harness cli-anything gimp")) {
  throw new Error("Dashboard does not expose the CLI-Anything harness import command.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/import-harness"')) {
  throw new Error("Dashboard does not wire CLI-Anything harness import to the daemon API.");
}

if (!html.includes("python -m cbn plugin import-harness cli-anything gimp --from-market")) {
  throw new Error("Dashboard does not expose the CLI-Anything market metadata import command.");
}

if (!html.includes("python -m cbn plugin adapt-harness cli-anything gimp --from-market")) {
  throw new Error("Dashboard does not expose the CLI-Anything adaptation report command.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/adapt-harness"')) {
  throw new Error("Dashboard does not wire CLI-Anything adaptation to the daemon API.");
}

if (!html.includes("python -m cbn plugin prepare-harness cli-anything gimp --from-market")) {
  throw new Error("Dashboard does not expose the CLI-Anything harness preparation report command.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/prepare-harness"')) {
  throw new Error("Dashboard does not wire CLI-Anything preparation to the daemon API.");
}

if (!html.includes("python -m cbn plugin evaluate-harness cli-anything mermaid")) {
  throw new Error("Dashboard does not expose the CLI-Anything candidate evaluation command.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/evaluate-harness"')) {
  throw new Error("Dashboard does not wire CLI-Anything candidate evaluation to the daemon API.");
}

if (!html.includes("python -m cbn plugin harness cli-anything status gimp --from-market")) {
  throw new Error("Dashboard does not expose the CLI-Anything harness status command.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/harness"')) {
  throw new Error("Dashboard does not wire CLI-Anything harness lifecycle to the daemon API.");
}

if (!html.includes("python -m cbn plugin harness cli-anything install gimp")) {
  throw new Error("Dashboard does not expose the managed CLI-Anything harness install command.");
}

if (!html.includes("python -m cbn plugin harness cli-anything uninstall gimp")) {
  throw new Error("Dashboard does not expose the managed CLI-Anything harness uninstall command.");
}

if (!html.includes("python -m cbn event tail")) {
  throw new Error("Dashboard does not expose the event bus tail command.");
}

if (!html.includes('data-api-path="/events"')) {
  throw new Error("Dashboard does not wire the event bus to the daemon API.");
}

if (!html.includes("python -m cbn artifact list")) {
  throw new Error("Dashboard does not expose the runtime artifact list command.");
}

if (!html.includes('data-api-path="/artifacts"')) {
  throw new Error("Dashboard does not wire artifacts to the daemon API.");
}

if (!html.includes("python -m cbn approvals list")) {
  throw new Error("Dashboard does not expose the approval queue list command.");
}

if (!html.includes('data-api-path="/approvals?status=pending"')) {
  throw new Error("Dashboard does not wire approvals to the daemon API.");
}

if (!html.includes("python -m cbn workflow run workflows/example.json --dry-run")) {
  throw new Error("Dashboard does not expose the runnable workflow dry-run command.");
}

if (!html.includes('data-api-path="/workflows/run"')) {
  throw new Error("Dashboard does not wire workflow execution to the daemon API.");
}

if (!html.includes("python -m cbn workflow run workflows/message-routing.example.json --dry-run")) {
  throw new Error("Dashboard does not expose the BridgeMessage routing workflow command.");
}

if (!html.includes("python -m cbn parser list")) {
  throw new Error("Dashboard does not expose the parser registry list command.");
}

if (!html.includes("python -m cbn registry search")) {
  throw new Error("Dashboard does not expose the capability registry search command.");
}

if (!html.includes("python -m cbn registry validate manifests")) {
  throw new Error("Dashboard does not expose manifest validation.");
}

if (!html.includes('data-api-path="/registry/validate"')) {
  throw new Error("Dashboard does not wire manifest validation to the daemon API.");
}

if (!html.includes("python -m cbn protocol export all")) {
  throw new Error("Dashboard does not expose the protocol export command.");
}

if (!html.includes('data-api-path="/protocols?target=all"')) {
  throw new Error("Dashboard does not wire protocol export to the daemon API.");
}

if (!html.includes("python -m cbn message validate")) {
  throw new Error("Dashboard does not expose the BridgeMessage validate command.");
}

if (!html.includes("python -m cbn message select")) {
  throw new Error("Dashboard does not expose the BridgeMessage selector command.");
}

if (!html.includes("python -m cbn message args")) {
  throw new Error("Dashboard does not expose the BridgeMessage argv mapping command.");
}

if (!js.includes("stageCommand")) {
  throw new Error("Dashboard script does not stage commands.");
}

if (!js.includes("fetch(apiUrl(path), options)")) {
  throw new Error("Dashboard script does not call the daemon API.");
}

if (!js.includes("data-api-path")) {
  throw new Error("Dashboard script does not bind daemon API actions.");
}

if (!css.includes(".control-grid")) {
  throw new Error("Dashboard stylesheet is missing the control grid.");
}

if (!css.includes("input")) {
  throw new Error("Dashboard stylesheet is missing the daemon API input styling.");
}

if (pkg.scripts?.serve !== "node scripts/serve-static.mjs") {
  throw new Error("Dashboard package does not expose the local static serve script.");
}

console.log("dashboard static check ok");
