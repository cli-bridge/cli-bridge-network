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
  "Candidate Summary",
  "Operation Detail",
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

if (!html.includes("python -m cbn plugin check-update cli-anything")) {
  throw new Error("Dashboard does not expose the CLI-Anything local update check command.");
}

if (!html.includes("python -m cbn plugin check-update cli-anything --remote")) {
  throw new Error("Dashboard does not expose the CLI-Anything remote update check command.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/update-check"')) {
  throw new Error("Dashboard does not wire CLI-Anything local update checks to the daemon API.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/update-check?remote=true"')) {
  throw new Error("Dashboard does not wire CLI-Anything remote update checks to the daemon API.");
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

if (!html.includes("python -m cbn plugin candidates cli-anything --query file --limit 20 --compact")) {
  throw new Error("Dashboard does not expose compact CLI-Anything candidate ranking.");
}

if (!html.includes("python -m cbn plugin candidates cli-anything --query file --limit 20 --with-probes --compact")) {
  throw new Error("Dashboard does not expose compact probed CLI-Anything candidate ranking.");
}

if (!html.includes("python -m cbn plugin install-queue cli-anything --query file --limit 20 --max-installs 5")) {
  throw new Error("Dashboard does not expose the CLI-Anything market install queue.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/install-queue"')) {
  throw new Error("Dashboard does not wire the CLI-Anything market install queue to the daemon API.");
}

if (!html.includes("python -m cbn plugin blocked-plan cli-anything --harness n8n --harness py4csr --harness unimol_tools")) {
  throw new Error("Dashboard does not expose the CLI-Anything blocked harness plan.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/blocked-plan"')) {
  throw new Error("Dashboard does not wire the CLI-Anything blocked harness plan to the daemon API.");
}

if (!html.includes("python -m cbn plugin repair-plan cli-anything py4csr --from-market")) {
  throw new Error("Dashboard does not expose the CLI-Anything entrypoint repair plan.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/repair-plan"')) {
  throw new Error("Dashboard does not wire the CLI-Anything entrypoint repair plan to the daemon API.");
}

if (!html.includes("python -m cbn plugin repair-entrypoint cli-anything py4csr --from-market")) {
  throw new Error("Dashboard does not expose the CLI-Anything entrypoint repair execution plan.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/repair-entrypoint"')) {
  throw new Error("Dashboard does not wire the CLI-Anything entrypoint repair execution to the daemon API.");
}

if (!html.includes("python -m cbn plugin adapter-targets cli-anything py4csr --from-market --limit 10")) {
  throw new Error("Dashboard does not expose CLI-Anything adapter target discovery.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/adapter-targets"')) {
  throw new Error("Dashboard does not wire CLI-Anything adapter target discovery to the daemon API.");
}

if (!html.includes("python -m cbn plugin adapter-smoke cli-anything py4csr --from-market --module py4csr.plotting.sas_compatible_rtf_generator")) {
  throw new Error("Dashboard does not expose CLI-Anything adapter target smoke planning.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/adapter-smoke"')) {
  throw new Error("Dashboard does not wire CLI-Anything adapter target smoke planning to the daemon API.");
}

if (!html.includes("python -m cbn plugin repair-entrypoint cli-anything py4csr --from-market --module py4csr.tables.rtf_formatter --require-smoke")) {
  throw new Error("Dashboard does not expose CLI-Anything smoke-gated entrypoint repair planning.");
}

if (!html.includes("python -m cbn plugin live-verification cli-anything")) {
  throw new Error("Dashboard does not expose the CLI-Anything live verification command.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/live-verification"')) {
  throw new Error("Dashboard does not wire CLI-Anything live verification to the daemon API.");
}

if (!html.includes("python -m cbn plugin verify-harness cli-anything 3mf --smoke-suite --smoke-extra-arg=--help --no-workflows")) {
  throw new Error("Dashboard does not expose the CLI-Anything harness smoke-suite verification command.");
}

if (!html.includes('data-api-body=\'{"harness_name":"3mf","from_market":true,"include_workflows":false,"run_smoke_suite":true,"smoke_extra_args":["--help"]}\'')) {
  throw new Error("Dashboard does not wire CLI-Anything harness smoke-suite verification to the daemon API.");
}

if (!html.includes("python -m cbn plugin onboard-harness cli-anything gimp --from-market")) {
  throw new Error("Dashboard does not expose the CLI-Anything harness onboarding preview command.");
}

if (!html.includes('data-api-path="/plugins/cli-anything/onboard-harness"')) {
  throw new Error("Dashboard does not wire CLI-Anything harness onboarding to the daemon API.");
}

if (!html.includes("python -m cbn plugin onboard-harness cli-anything gimp --from-market --write --yes")) {
  throw new Error("Dashboard does not expose confirmed CLI-Anything onboarding manifest write.");
}

if (!html.includes("python -m cbn plugin onboard-harness cli-anything 3mf --from-market --write --install --yes --smoke-suite --smoke-extra-arg=--help --no-workflows")) {
  throw new Error("Dashboard does not expose confirmed CLI-Anything onboarding install.");
}

if (!html.includes('data-api-body=\'{"harness_name":"3mf","from_market":true,"write":true,"install":true,"confirmed":true,"include_workflows":false,"run_smoke_suite":true,"smoke_extra_args":["--help"]}\'')) {
  throw new Error("Dashboard does not wire confirmed CLI-Anything onboarding install to the daemon API.");
}

if (!html.includes("python -m cbn plugin onboard-harness cli-anything 3mf --from-market --smoke-suite --smoke-extra-arg=--help --no-workflows")) {
  throw new Error("Dashboard does not expose CLI-Anything onboarding smoke-suite command.");
}

if (!html.includes('data-api-body=\'{"query":"file","limit":20,"compact":true}\'')) {
  throw new Error("Dashboard candidate ranking API body is not compact.");
}

if (!html.includes('data-api-body=\'{"query":"file","limit":20,"with_probes":true,"compact":true}\'')) {
  throw new Error("Dashboard probed candidate ranking API body is not compact.");
}

if (!html.includes('data-api-body=\'{"query":"file","limit":20,"max_installs":5,"include_blocked":true}\'')) {
  throw new Error("Dashboard install queue API body is not stable.");
}

if (!html.includes('data-api-body=\'{"harnesses":["n8n","py4csr","unimol_tools"]}\'')) {
  throw new Error("Dashboard blocked plan API body is not stable.");
}

if (!html.includes('data-api-body=\'{"harness_name":"py4csr","from_market":true}\'')) {
  throw new Error("Dashboard repair plan API body is not stable.");
}

if (!html.includes('data-api-body=\'{"harness_name":"py4csr","from_market":true,"limit":10}\'')) {
  throw new Error("Dashboard adapter target API body is not stable.");
}

if (!html.includes('data-api-body=\'{"harness_name":"py4csr","from_market":true,"module":"py4csr.plotting.sas_compatible_rtf_generator","smoke_args":["--help"],"timeout_seconds":10}\'')) {
  throw new Error("Dashboard adapter smoke API body is not stable.");
}

if (!html.includes('data-api-body=\'{"harness_name":"py4csr","from_market":true,"module":"py4csr.tables.rtf_formatter","require_smoke":true,"smoke_args":["--help"],"smoke_timeout_seconds":10}\'')) {
  throw new Error("Dashboard smoke-gated repair API body is not stable.");
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

if (!html.includes("python -m cbn workflow list")) {
  throw new Error("Dashboard does not expose the workflow catalog command.");
}

if (!html.includes('data-api-path="/workflows"')) {
  throw new Error("Dashboard does not wire the workflow catalog to the daemon API.");
}

if (!html.includes('data-api-path="/workflows/run"')) {
  throw new Error("Dashboard does not wire workflow execution to the daemon API.");
}

if (!html.includes("python -m cbn workflow run workflows/message-routing.example.json --dry-run")) {
  throw new Error("Dashboard does not expose the BridgeMessage routing workflow command.");
}

if (!html.includes("python -m cbn workflow run workflows/artifact-id-routing.example.json")) {
  throw new Error("Dashboard does not expose the artifact id routing workflow command.");
}

if (!html.includes("python -m cbn workflow run workflows/cli-anything-mermaid-routing.example.json")) {
  throw new Error("Dashboard does not expose the CLI-Anything Mermaid routing workflow command.");
}

if (!html.includes("python -m cbn workflow run workflows/cli-anything-macrocli-mermaid-routing.example.json")) {
  throw new Error("Dashboard does not expose the MacroCLI to Mermaid routing workflow command.");
}

if (!html.includes("python -m cbn parser list")) {
  throw new Error("Dashboard does not expose the parser registry list command.");
}

if (!html.includes("python -m cbn parser fixtures --parser-ref cli-anything.raw")) {
  throw new Error("Dashboard does not expose parser fixture verification.");
}

if (!html.includes('data-api-path="/parsers/fixtures?parser_ref=cli-anything.raw"')) {
  throw new Error("Dashboard does not wire parser fixture verification to the daemon API.");
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

if (!html.includes("python -m cbn protocol export-workflows all")) {
  throw new Error("Dashboard does not expose the protocol workflow export command.");
}

if (!html.includes('data-api-path="/protocols/workflows?target=all"')) {
  throw new Error("Dashboard does not wire workflow protocol exports to the daemon API.");
}

if (!html.includes('data-api-path="/protocols?target=all"')) {
  throw new Error("Dashboard does not wire protocol export to the daemon API.");
}

if (!html.includes("python -m cbn protocol check all --capability-id cli-anything.mermaid.set-diagram")) {
  throw new Error("Dashboard does not expose the protocol compatibility check command.");
}

if (!html.includes('data-api-path="/protocols/check?target=all&amp;capability_id=cli-anything.mermaid.set-diagram"')) {
  throw new Error("Dashboard does not wire protocol compatibility checks to the daemon API.");
}

if (!html.includes("python -m cbn protocol readiness")) {
  throw new Error("Dashboard does not expose the protocol readiness report command.");
}

if (!html.includes('data-api-path="/protocols/readiness"')) {
  throw new Error("Dashboard does not wire protocol readiness to the daemon API.");
}

if (!html.includes("python -m cbn protocol accept-workflow workflows/cli-anything-macrocli-mermaid-routing.example.json")) {
  throw new Error("Dashboard does not expose CLI-to-CLI workflow acceptance.");
}

if (!html.includes("python -m cbn protocol accept-workflow workflows/cli-anything-macrocli-mermaid-routing.example.json --run")) {
  throw new Error("Dashboard does not expose runtime CLI-to-CLI workflow acceptance.");
}

if (!html.includes('data-api-path="/protocols/accept-workflow"')) {
  throw new Error("Dashboard does not wire CLI-to-CLI workflow acceptance to the daemon API.");
}

if (!html.includes('data-api-body=\'{"workflow_path":"workflows/cli-anything-macrocli-mermaid-routing.example.json","run":true}\'')) {
  throw new Error("Dashboard does not wire runtime CLI-to-CLI workflow acceptance payload.");
}

if (!html.includes("python -m cbn protocol smoke-suite --capability-id git.version --workflow-path workflows/example.json --workflow-dry-run")) {
  throw new Error("Dashboard does not expose the protocol smoke suite command.");
}

if (!html.includes('data-api-path="/protocols/smoke-suite?capability_id=git.version&amp;workflow_path=workflows/example.json&amp;workflow_dry_run=true"')) {
  throw new Error("Dashboard does not wire protocol smoke suite to the daemon API.");
}

if (!html.includes("python -m cbn mcp serve --stdio")) {
  throw new Error("Dashboard does not expose the MCP stdio server command.");
}

if (!html.includes("python -m cbn mcp smoke --capability-id git.version")) {
  throw new Error("Dashboard does not expose the MCP stdio smoke command.");
}

if (!html.includes("python -m cbn mcp smoke-workflow --path workflows/example.json --dry-run")) {
  throw new Error("Dashboard does not expose the MCP workflow smoke command.");
}

if (!html.includes("python -m cbn a2a agent-card")) {
  throw new Error("Dashboard does not expose the A2A AgentCard command.");
}

if (!html.includes("python -m cbn a2a smoke --capability-id git.version")) {
  throw new Error("Dashboard does not expose the A2A smoke command.");
}

if (!html.includes("python -m cbn a2a smoke-workflow --path workflows/example.json --dry-run")) {
  throw new Error("Dashboard does not expose the A2A workflow smoke command.");
}

if (!html.includes("python -m cbn plugin evaluate-harness cli-anything macrocli")) {
  throw new Error("Dashboard does not expose the MacroCLI evaluation command.");
}

if (!html.includes("python -m cbn plugin harness cli-anything install macrocli --yes")) {
  throw new Error("Dashboard does not expose the MacroCLI install command.");
}

if (!html.includes("python -m cbn call cli-anything.macrocli.backends")) {
  throw new Error("Dashboard does not expose the MacroCLI verified backends command.");
}

if (!html.includes("python -m cbn acp serve --stdio")) {
  throw new Error("Dashboard does not expose the ACP stdio agent command.");
}

if (!html.includes("python -m cbn acp smoke --capability-id git.version")) {
  throw new Error("Dashboard does not expose the ACP stdio smoke command.");
}

if (!html.includes("python -m cbn acp smoke-workflow --path workflows/example.json --dry-run")) {
  throw new Error("Dashboard does not expose the ACP workflow smoke command.");
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

if (!js.includes("renderCandidateSummary")) {
  throw new Error("Dashboard script does not render compact CLI-Anything candidates.");
}

if (!js.includes("displayPayload")) {
  throw new Error("Dashboard script does not normalize large candidate API payloads for display.");
}

if (!js.includes("candidateSummaryFromCandidates")) {
  throw new Error("Dashboard script does not fall back from candidates when candidate_summary is absent.");
}

if (!js.includes("candidateAction")) {
  throw new Error("Dashboard script does not expose candidate follow-up actions.");
}

if (!js.includes("renderOperationDetail")) {
  throw new Error("Dashboard script does not render CLI-Anything operation details.");
}

if (!js.includes("operationBlockers")) {
  throw new Error("Dashboard script does not surface operation blockers.");
}

if (!js.includes("operationCommands")) {
  throw new Error("Dashboard script does not surface operation plan commands.");
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

if (!css.includes(".candidate-summary")) {
  throw new Error("Dashboard stylesheet is missing candidate summary styling.");
}

if (!css.includes(".operation-detail")) {
  throw new Error("Dashboard stylesheet is missing operation detail styling.");
}

if (!css.includes("input")) {
  throw new Error("Dashboard stylesheet is missing the daemon API input styling.");
}

if (pkg.scripts?.serve !== "node scripts/serve-static.mjs") {
  throw new Error("Dashboard package does not expose the local static serve script.");
}

console.log("dashboard static check ok");
