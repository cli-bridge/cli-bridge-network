# CLI Bridge Network

[简体中文](README.md) | English

CLI Bridge Network (CBN) is a local-first capability network for unifying command-line tools, parsers, MCP services, Agent CLI contracts, and automation workflows into a declarative, auditable, and routable capability layer.

It does not replace existing CLIs. Instead, it adds a stable engineering shell around them: capability manifests, policy and approval checks, controlled execution, structured messages, artifacts, events, audit logs, workflow orchestration, and protocol or frontend-facing adapters.

> This project is currently an MVP / rapidly evolving skeleton. The repository already contains a runnable Python CLI, local HTTP daemon, Workflow Studio frontend, Agent CLI Contract boundary, TypeScript package boundaries, and Rust workspace skeleton. Protocol-related features currently focus on descriptor export, checks, smoke tests, and adapter boundaries. They should not be interpreted as complete wire-compatible MCP / A2A / ACP servers.

## Table of Contents

- [Project Positioning](#project-positioning)
- [Use Cases](#use-cases)
- [Core Flow](#core-flow)
- [Feature Overview](#feature-overview)
- [Repository Layout](#repository-layout)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Usage](#cli-usage)
- [Local Daemon and API](#local-daemon-and-api)
- [Workflow Studio and Desktop Entry](#workflow-studio-and-desktop-entry)
- [Manifest and Capability Registry](#manifest-and-capability-registry)
- [Policy, Approval, and Execution Safety](#policy-approval-and-execution-safety)
- [Parsers, Messages, Artifacts, Events, and Audit](#parsers-messages-artifacts-events-and-audit)
- [Workflows](#workflows)
- [Protocols and Agent CLI Contract](#protocols-and-agent-cli-contract)
- [Plugins and External Adapters](#plugins-and-external-adapters)
- [Configuration and Runtime Data](#configuration-and-runtime-data)
- [Development and Testing](#development-and-testing)
- [FAQ](#faq)
- [License](#license)

## Project Positioning

CBN focuses on turning existing tools into a reliable local capability network.

Many automation projects start as a collection of scripts, commands, batch files, small HTTP services, browser automation flows, model tools, downloaders, parsers, and temporary glue code. They may work, but they usually cannot answer these questions cleanly:

- What are this tool's input parameters, output shape, and risk level?
- Can the command be dry-run before real execution?
- Which actions require user confirmation?
- Can the result be referenced reliably by the next step?
- Where are errors, artifacts, events, and audit records stored?
- Can this capability be reused by a frontend, MCP, an agent, or another protocol?
- Can a temporary local script gradually become a maintainable capability package?

CLI Bridge Network is designed around these questions. It abstracts a tool into a declarative capability, then connects tools into a traceable execution network through controlled execution, parsing, artifact archival, event publishing, audit logging, and workflow routing.

## Use Cases

CBN is useful when:

- You have multiple local CLIs, scripts, batch files, or utilities and want a single registry, invocation, and audit layer.
- You want to see the command, arguments, risk level, and dry-run result before real execution.
- You want to convert CLI output into structured messages instead of forcing downstream steps to parse raw text.
- You want to compose multiple CLIs into a DAG workflow and feed upstream output into downstream arguments.
- You want a frontend control surface for local tools instead of memorizing terminal commands.
- You want a protocol-neutral internal model that can later project into MCP, A2A, ACP, Agent CLI Contract, or other boundaries.
- You are prototyping a local agent, tool network, workflow runtime, or protocol adapter and need a standard skeleton.

CBN should not be understood as:

- A remote SaaS platform.
- A generic shell hosting service.
- A production server with full wire compatibility for every external protocol.
- An automatic executor that bypasses permissions, approvals, or user confirmation.

## Core Flow

The core CBN path can be summarized as:

```text
ToolManifest
  -> Registry
  -> Policy / Approval
  -> CapabilityExecutor
  -> Parser
  -> BridgeMessage
  -> Artifact / Event / Audit
  -> Workflow argsFrom
  -> Protocol / API / Studio / Plugin
```

Mapped to repository directories:

- `manifests/` declares capabilities.
- `cbn_runtime/` builds the runtime context.
- `cbn_execution/` handles controlled execution, policy checks, parsing, and artifact writes.
- `cbn_policy/` and `cbn_approval/` handle risk and approval decisions.
- `cbn_parsers/` parses CLI output.
- `cbn_artifacts/`, `cbn_events/`, and `cbn_audit/` store artifacts, events, and audit logs.
- `cbn_workflow/` organizes capabilities into executable DAGs.
- `api_server/` exposes the local HTTP API.
- `frontend/` provides Workflow Studio / Electron UI.
- `cbn_protocol/`, `external_protocols/`, `packages/`, and `crates/` carry protocol and cross-language boundaries.

## Feature Overview

| Feature | Status | Description |
| --- | --- | --- |
| Capability registry | Available | Loads ToolManifest files from `manifests/` and local runtime overlays. |
| CLI invocation | Available | Calls capabilities with `python -m cbn call <capability>` and supports dry-run. |
| Policy and approval | Available | High-risk, external side-effect, or confirmation-required operations can enter an approval flow. |
| Output parsing | Available | Parsers convert stdout / stderr into structured `BridgeMessage` objects. |
| Artifact management | Available | Invocation results, parsed output, and related files can be stored in the artifact store. |
| Event bus | Available | Runtime actions can publish events for the frontend and automation consumers. |
| Audit log | Available | Capability calls, approvals, and workflow executions leave audit records. |
| Workflow DAG | Available | Connects tasks with `needs` and `argsFrom`. |
| Local daemon | Available | Standard-library HTTP server for registry, workflow, artifact, approval, and related APIs. |
| Workflow Studio | Available | Vue + Vite + Electron frontend for managing and running workflows visually. |
| Agent CLI Contract | Boundary available | Supports `AgentCliCard` / `RunReceipt` contracts, fixtures, and smoke scripts. |
| MCP / A2A / ACP | MVP boundary | Provides descriptor export, checks, matrices, and smoke entry points; not a complete protocol server. |
| CLI-Anything plugin | Boundary available | Provides registration, preflight, plan, and installation boundaries for external CLI hubs / adapters. |
| TypeScript packages | Skeleton | `packages/*` defines cross-language core, network, MCP, and adapter boundaries. |
| Rust crates | Skeleton | `crates/*` is a future boundary for native Rust runtime or components. |

## Repository Layout

| Path | Purpose |
| --- | --- |
| `cbn/` | Python CLI entrypoint, command parsing, and subcommand dispatch. |
| `cbn_core/` | Core types, message model, and shared protocol objects. |
| `cbn_runtime/` | Runtime context assembly for registry, executor, workflow runner, stores, and plugin runner. |
| `cbn_execution/` | Capability executor for manifest lookup, policy, approval, stdio / PTY / in-process / MCP dispatch, parsers, and artifacts. |
| `cbn_config/` | Paths, runtime configuration, and local directory conventions. |
| `cbn_policy/` | Risk policy, pre-execution checks, and approval decisions. |
| `cbn_approval/` | Approval requests, approval status, and local approval storage. |
| `cbn_parsers/` | Output parser registry, parser execution, and fixture recording. |
| `cbn_artifacts/` | Artifact storage, artifact metadata, and traceable references. |
| `cbn_events/` | Event bus and event readers. |
| `cbn_audit/` | Audit log writes and queries. |
| `cbn_workflow/` | Workflow validation, topological sorting, argument routing, execution, and summaries. |
| `cbn_protocol/` | MCP / A2A / ACP descriptors and adapter boundaries. |
| `cbn_plugins/` | Plugin operation runner and external plugin boundaries. |
| `cbn_tools/` | Built-in helper tooling. |
| `api_server/` | Local HTTP daemon for registry, workflow, artifact, approval, protocol, and related APIs. |
| `frontend/` | Vue 3 + Vite + Electron Workflow Studio frontend. |
| `packages/` | TypeScript workspace packages for future SDK / MCP / adapter boundaries. |
| `crates/` | Rust workspace skeleton for future Rust components. |
| `external_protocols/agent-cli-contract/` | Agent CLI Contract, fixtures, Python package, and smoke scripts. |
| `manifests/` | Default capability manifests. |
| `parser_fixtures/` | Parser tests and recorded fixtures. |
| `workflows/` | Example workflows. |
| `custom_adapters/` | Local custom adapter extension point, similar in spirit to ComfyUI `custom_nodes`. |
| `external_plugins/` | External plugin installation location, usually not committed to Git. |
| `runtime/` | Local runtime data, artifacts, events, audit logs, and approval state, usually not committed to Git. |
| `tests-unit/` | Python unit tests. |
| `main.py`, `server.py`, `nodes.py`, `protocol.py` | Compatibility or demo entrypoints. The recommended CLI entrypoint is still `python -m cbn` or installed `cbn`. |

## Requirements

### Required

| Component | Requirement |
| --- | --- |
| Python | `>= 3.10` |
| pip | Needed for editable installs and optional dependencies. |
| Git | Example manifests include Git capabilities, and some smoke checks depend on Git. |

### Optional

| Component | Purpose |
| --- | --- |
| Node.js / npm | Runs `frontend/`, Electron, and TypeScript package checks. |
| Rust toolchain | Checks the `crates/*` workspace. |
| `pywinpty` | Required for PTY execution mode on Windows when using the `.[pty]` extra. |
| `ffprobe` | Required when using media inspection manifests. |
| External CLIs / plugins | Capabilities such as `cli-anything`, third-party tools, and MCP services only work when their dependencies are installed locally. |

### Windows Encoding Recommendation

The repository expects UTF-8 for reading and writing files. In Windows PowerShell, set:

```powershell
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

## Installation

### 1. Clone the Repository

```powershell
git clone https://github.com/cli-bridge/cli-bridge-network.git
cd cli-bridge-network
```

If you are already inside a local development checkout, use that checkout directly.

### 2. Create a Python Virtual Environment

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
```

### 3. Install the Python Package

Editable install is recommended:

```powershell
python -m pip install -e .
```

After installation, the `cbn` console script is available:

```powershell
cbn --version
cbn health
```

You can also run directly from source without relying on the console script:

```powershell
python -m cbn --version
python -m cbn health
```

### 4. Install Optional PTY Dependencies

On Windows, install the PTY extra when PTY execution mode is needed:

```powershell
python -m pip install -e ".[pty]"
```

### 5. requirements.txt

`requirements.txt` is intentionally empty right now. The runtime is currently stdlib-first, and package metadata lives in `pyproject.toml`.

If runtime dependencies are added later, install them with:

```powershell
python -m pip install -r requirements.txt
```

### 6. Install Frontend Dependencies

```powershell
npm install
npm --workspace frontend run check
```

### 7. Check the Rust Workspace

The Rust side is currently a workspace skeleton. If you have a Rust toolchain installed, run:

```powershell
cargo check --workspace
```

## Quick Start

### Check Version and Health

```powershell
python -m cbn --version
python -m cbn health
```

The health command returns JSON with the project name, version, status, and daemon token configuration summary.

### List Available Capabilities

```powershell
python -m cbn registry list
```

The registry loads capabilities from default manifests and local runtime overlays. Output may vary between machines because external plugins, local manifests, runtime overlays, and installed CLIs affect the final capability list.

### Dry-run a Capability

```powershell
python -m cbn call git.version --dry-run
```

Dry-run constructs the command, generates structured messages, and writes audit records without performing real external side-effect commands. New manifests and workflows should be validated with dry-run first.

### Inspect Example Workflows

```powershell
python -m cbn workflow list
python -m cbn workflow inspect workflows\example.json
```

### Start the Local Daemon

```powershell
python -m cbn daemon routes
python -m cbn daemon serve --host 127.0.0.1 --port 8787
```

### Start Workflow Studio

```powershell
npm install
npm run app:dev
```

On Windows, you can also use:

```powershell
.\start-electron.bat
```

## CLI Usage

The main CBN entrypoint is:

```powershell
python -m cbn <command> [options]
```

If you have run `python -m pip install -e .`, you can also use:

```powershell
cbn <command> [options]
```

### Basic Commands

| Command | Purpose |
| --- | --- |
| `python -m cbn --help` | Show top-level help. |
| `python -m cbn --version` | Show the CBN version. |
| `python -m cbn health` | Check local runtime health. |
| `python -m cbn paths` | Show project and runtime paths. |
| `python -m cbn nodes` | Show node-related information. |

### Registry and Capability Calls

| Command | Purpose |
| --- | --- |
| `python -m cbn registry list` | List loaded capabilities. |
| `python -m cbn registry search <keyword>` | Search capabilities. |
| `python -m cbn registry inspect <capability-id>` | Inspect a capability manifest. |
| `python -m cbn registry validate` | Validate manifests. |
| `python -m cbn call <capability-id> --dry-run` | Call a capability in dry-run mode. |
| `python -m cbn call <capability-id> --arg name=value` | Call a capability with arguments. |

Example:

```powershell
python -m cbn registry inspect git.version
python -m cbn call git.version --dry-run
```

### Audit, Events, and Artifacts

| Command | Purpose |
| --- | --- |
| `python -m cbn audit tail` | Show recent audit records. |
| `python -m cbn event tail` | Show recent events. |
| `python -m cbn artifact list` | List artifacts. |
| `python -m cbn artifact inspect <artifact-id>` | Inspect an artifact. |

### Parsers and Fixtures

| Command | Purpose |
| --- | --- |
| `python -m cbn parser list` | List parsers. |
| `python -m cbn parser inspect <parser-id>` | Inspect a parser. |
| `python -m cbn record-parser-fixture ...` | Record a parser fixture. |

### Workflow

| Command | Purpose |
| --- | --- |
| `python -m cbn workflow list` | List workflow JSON files. |
| `python -m cbn workflow inspect <workflow.json>` | Inspect a workflow. |
| `python -m cbn workflow validate <workflow.json>` | Validate a workflow. |
| `python -m cbn workflow plan <workflow.json>` | Print an execution plan. |
| `python -m cbn workflow run <workflow.json> --dry-run` | Run a workflow in dry-run mode. |
| `python -m cbn workflow run <workflow.json>` | Execute a workflow. |

Example:

```powershell
python -m cbn workflow inspect workflows\example.json
python -m cbn workflow run workflows\example.json --dry-run
```

### Protocol

| Command | Purpose |
| --- | --- |
| `python -m cbn protocol list` | Show protocol descriptors. |
| `python -m cbn protocol export <protocol>` | Export a protocol description. |
| `python -m cbn protocol check <protocol>` | Check a protocol boundary. |
| `python -m cbn protocol matrix` | Show the protocol capability matrix. |
| `python -m cbn protocol readiness` | Show protocol readiness. |

Current protocol commands should be understood as MVP descriptor, export, check, and smoke boundaries. `python -m cbn protocol list` reports the wire compatibility status.

### Import and Plugins

| Command | Purpose |
| --- | --- |
| `python -m cbn import ...` | Import capabilities from commands, MCP, skills, Agent CLI Cards, CLI-Anything, and related sources. |
| `python -m cbn plugin list` | List plugins. |
| `python -m cbn plugin info <plugin>` | Inspect plugin information. |
| `python -m cbn plugin plan <plugin>` | Show a plugin plan. |
| `python -m cbn plugin preflight <plugin>` | Run plugin preflight checks. |

### Daemon

| Command | Purpose |
| --- | --- |
| `python -m cbn daemon routes` | List local API routes. |
| `python -m cbn daemon serve --host 127.0.0.1 --port 8787` | Start the local HTTP daemon. |

### Network

| Command | Purpose |
| --- | --- |
| `python -m cbn network ...` | Access network package, quickstart, entry profile, consumer manifest, acceptance, verify, studio-link, and related helper commands. |

## Local Daemon and API

The CBN daemon is a local-first standard-library HTTP service. It connects the CLI, Workflow Studio, approval panel, artifact queries, and protocol boundaries.

List routes:

```powershell
python -m cbn daemon routes
```

Start the service:

```powershell
python -m cbn daemon serve --host 127.0.0.1 --port 8787
```

Common local URLs:

| Service | Default URL |
| --- | --- |
| CBN daemon | `http://127.0.0.1:8787` |
| Workflow Studio | `http://127.0.0.1:5177` |
| Dashboard / Vite dev | `http://127.0.0.1:5173` |

Daemon API categories include:

- Registry and capability queries.
- Capability calls and dry-run.
- Workflow list, inspect, execution, and run status.
- Artifact, event, and audit queries.
- Approval creation, inspection, approval, and rejection.
- Parser, protocol, plugin, network, and MCP ingress boundaries.
- Thread, favorite, card, and local UI state.

### Daemon Session Token

The local daemon supports session token configuration:

| Environment variable | Purpose |
| --- | --- |
| `CBN_DAEMON_SESSION_TOKEN` | Sets the daemon token. |
| `CBN_DAEMON_REQUIRE_SESSION_TOKEN` | Controls whether a token is required. |

Clients can pass the token with:

- `X-CBN-Session: <token>`
- `Authorization: Bearer <token>`

During local development, loopback hosts may run without a required token. For non-local or stricter environments, enable token enforcement.

## Workflow Studio and Desktop Entry

`frontend/` is the graphical workspace for CBN. It uses Vue 3, Vite, LiteGraph, and Electron.

Common commands:

```powershell
npm install
npm --workspace frontend run check
npm --workspace frontend run app:dev
```

From the repository root:

```powershell
npm run app:dev
```

Windows desktop entry:

```powershell
.\start-electron.bat
```

`start-electron.bat` sets the UTF-8 code page and daemon URL environment variables, then starts the Electron development workflow.

Workflow Studio is intended for:

- Browsing the capability registry.
- Composing workflow nodes.
- Inspecting node execution status.
- Observing events, artifacts, and audit records.
- Handling approval requests that require user confirmation.
- Acting as the visual entrypoint for the local CLI capability network.

## Manifest and Capability Registry

CBN describes capabilities with ToolManifest files. A manifest usually defines:

- Capability id.
- Name and description.
- Argument schema.
- Execution mode.
- Output parser.
- Risk level.
- Dry-run support.
- Approval requirements.
- Artifact and message mapping.

Default manifests live in:

```text
manifests/
```

The runtime may also load local overlay manifests. Overlays are useful for machine-specific, local experimental, or non-committed capabilities.

Common registry commands:

```powershell
python -m cbn registry list
python -m cbn registry inspect git.version
python -m cbn registry validate
```

Recommended flow for adding a capability:

1. Write the smallest possible manifest.
2. Validate it with `registry validate`.
3. Check command construction with `call <id> --dry-run`.
4. Add or reuse a parser.
5. Record parser fixtures.
6. Connect it to workflows or the frontend.

## Policy, Approval, and Execution Safety

CBN does not simply pass arbitrary strings to a shell. Execution goes through:

```text
manifest lookup -> policy decision -> approval check -> execution -> parse -> artifact -> audit
```

Safety-related design choices:

- Dry-run-first is encouraged by default.
- High-risk capabilities can be blocked by policy.
- Capabilities requiring user confirmation create approval requests.
- External side-effect operations can require explicit approval.
- Execution results are written to the audit log.
- Output is converted into structured messages by parsers to reduce downstream misinterpretation.
- Local `.env`, runtime data, and external plugin directories should not be committed to Git.

Approval help:

```powershell
python -m cbn approvals --help
```

## Parsers, Messages, Artifacts, Events, and Audit

One of CBN's main goals is to make CLI output traceable and machine-readable rather than leaving it as raw text.

### BridgeMessage

`BridgeMessage` is the structured message format used internally by CBN to pass execution results. It usually contains:

- Invocation information.
- Status.
- stdout / stderr summary.
- Parser output.
- Artifact references.
- Error details.
- Fields that workflow `argsFrom` selectors can reference.

### Artifact

Artifacts store execution results and traceable outputs, for example:

- Structured JSON output.
- Parser results.
- Command execution summaries.
- Intermediate workflow results.
- References to files generated by external tools.

### Event

Events allow the frontend and automation consumers to observe runtime behavior, for example:

- capability started.
- capability completed.
- workflow task completed.
- approval requested.
- artifact created.

### Audit

The audit log answers: when, who, with which arguments, called which capability, and what happened.

Common commands:

```powershell
python -m cbn audit tail
python -m cbn event tail
python -m cbn artifact list
```

## Workflows

Workflows describe DAGs in JSON. Each task can call a capability, declare dependencies with `needs`, and extract arguments from upstream `BridgeMessage` objects through `argsFrom`.

Example workflows live in:

```text
workflows/
```

Common commands:

```powershell
python -m cbn workflow list
python -m cbn workflow inspect workflows\example.json
python -m cbn workflow validate workflows\example.json
python -m cbn workflow plan workflows\example.json
python -m cbn workflow run workflows\example.json --dry-run
```

The workflow runner handles:

- JSON structure validation.
- Unique task ids.
- Dependency graph topological sorting.
- Cycle detection.
- Upstream result selectors.
- Dry-run propagation.
- Statuses such as blocked, failed, skipped, and completed.

Good workflow candidates include:

- Check the environment before running a tool.
- Generate a file before another tool consumes it.
- Call a CLI and pass parsed output to downstream nodes.
- Compose local checks into an acceptance flow.

## Protocols and Agent CLI Contract

CBN keeps multiple protocol boundaries while keeping its internal core model protocol-neutral.

### MCP / A2A / ACP

Protocol entrypoints:

```powershell
python -m cbn protocol list
python -m cbn protocol matrix
python -m cbn protocol readiness
```

The current protocol implementation focuses on MVP descriptors, export, checks, smoke suites, and adapter boundaries. The project explicitly reports `wire_compatible` state to avoid confusing descriptor export with a full protocol server.

### Agent CLI Contract

Agent CLI Contract lives in:

```text
external_protocols/agent-cli-contract/
```

It defines two key concepts:

| Concept | Description |
| --- | --- |
| `AgentCliCard` | Describes an agent CLI capability card. CBN can map it to a ToolManifest. |
| `RunReceipt` | Describes a single agent CLI run result. CBN can map it to BridgeMessage, artifacts, audit records, and events. |

Contract smoke test:

```powershell
python external_protocols\agent-cli-contract\scripts\conformance_smoke.py
```

Python validation example:

```powershell
$env:PYTHONPATH = "external_protocols\agent-cli-contract\python"
python -m agent_cli_contract validate card external_protocols\agent-cli-contract\fixtures\agent-cli-card.valid.json
python -m agent_cli_contract validate receipt external_protocols\agent-cli-contract\fixtures\run-receipt.valid.json
```

Node check:

```powershell
node external_protocols\agent-cli-contract\scripts\check.mjs
```

## Plugins and External Adapters

CBN can connect external tool ecosystems through plugins and adapters.

Related directories:

| Path | Purpose |
| --- | --- |
| `cbn_plugins/` | Plugin operation runner. |
| `plugins/` | Plugin metadata or built-in plugin content. |
| `external_plugins/` | Local external plugin installation directory, usually not committed to Git. |
| `custom_adapters/` | Custom adapter extension point. |
| `packages/adapter-cli-anything/` | CLI-Anything / CLI-Hub adapter package boundary. |

Plugin commands:

```powershell
python -m cbn plugin list
python -m cbn plugin info cli-anything
python -m cbn plugin preflight cli-anything
```

Whether a plugin is usable depends on whether the corresponding external tools, virtual environments, Node packages, or credentials are installed locally.

## Configuration and Runtime Data

### Local Configuration

`.env` is for local environment variables and should not be committed to Git. Do not hardcode private tokens, absolute machine paths, accounts, cookies, or machine-specific settings in README files, manifests, or test fixtures.

### Runtime Directory

`runtime/` stores local runtime state, for example:

- audit logs.
- events.
- artifacts.
- approval store.
- local manifest overlays.
- plugin runtime state.

These files are usually machine-specific or generated during execution and should not be committed as source.

### External Plugin Directory

`external_plugins/` is intended for external tool hubs, adapters, vendor runtimes, or experimental plugins. Usually only `.gitkeep` should be tracked while actual contents are installed locally.

### Manifests and Local Overlays

Reusable capabilities should go into `manifests/`. Machine-specific capabilities, private paths, experimental commands, or temporary integrations should live in runtime overlays or ignored local config.

## Development and Testing

### Python Checks

```powershell
python -m cbn health
python -m unittest discover tests-unit
```

The root `package.json` also provides Python check scripts:

```powershell
npm run check:python
npm run check:cbn
```

### Frontend Checks

```powershell
npm --workspace frontend run check
```

### Agent CLI Contract Checks

```powershell
python external_protocols\agent-cli-contract\scripts\conformance_smoke.py
node external_protocols\agent-cli-contract\scripts\check.mjs
```

### Rust Checks

```powershell
cargo check --workspace
```

### Recommended Development Flow

1. Write or update a manifest.
2. Run `python -m cbn registry validate`.
3. Run `python -m cbn call <capability-id> --dry-run`.
4. Add parser fixtures.
5. Run relevant `tests-unit` tests.
6. If workflows are involved, run `workflow inspect`, `workflow validate`, and `workflow run --dry-run`.
7. If the frontend is involved, run `npm --workspace frontend run check`.
8. If protocol boundaries are involved, run the relevant `protocol` or `agent-cli-contract` smoke checks.

### Verified Basic Commands

The following commands are baseline validation entrypoints for the current project structure:

```powershell
python -m cbn --version
python -m cbn health
python -m cbn registry list
python -m cbn call git.version --dry-run
python -m cbn protocol list
python -m cbn workflow list
python -m cbn workflow inspect workflows\example.json
python -m cbn daemon routes
npm --workspace frontend run check
```

## FAQ

### Is this a CLI tool or a frontend app?

Both. `python -m cbn` is the core CLI and runtime entrypoint. `frontend/` is Workflow Studio, a visual interface for the same capability network.

### Why does registry output differ between machines?

The registry loads default manifests, local overlays, external plugins, and discoverable tools. Some capabilities depend on whether the corresponding CLI, plugin, or runtime is installed locally.

### Does dry-run write files?

Dry-run should not execute real external side-effect commands, but it may still write CBN's own local runtime records such as artifacts, events, or audit entries for debugging and tracing.

### Why is `requirements.txt` empty?

The current Python runtime is intentionally stdlib-first. Dependencies and package metadata are primarily defined in `pyproject.toml`. `requirements.txt` is reserved for future runtime dependencies.

### Do protocol commands mean full MCP / A2A / ACP implementations?

No. Current protocol commands mainly provide descriptor export, checks, matrices, readiness, and smoke boundaries. Use command output as the source of truth for wire compatibility status.

### Should `.env`, `runtime/`, or `external_plugins/` be committed?

Usually no. These files or directories may contain machine-specific state, private paths, tokens, logs, artifacts, or external tool installations.

### Where should I start when adding a CLI capability?

Start from an existing manifest in `manifests/`, write the smallest possible declaration, then validate it with `registry validate` and `call --dry-run`. Add a parser only when downstream steps need structured output.

## License

This project is released under the [MIT License](LICENSE).
