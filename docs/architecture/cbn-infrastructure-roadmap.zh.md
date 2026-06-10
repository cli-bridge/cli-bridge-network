# CBN Infrastructure Roadmap

## 产品定位

CBN 的 MVP 目标不是继续扩展按钮式 CLI 控制台，而是形成一套低门槛
CLI/Agent 基础设施：外部 CLI 或 Agent 通过稳定 contract 接入，运行时通过
BridgeMessage、Artifact、Event、Audit 和 Workflow selector 完成可观察的 CLI-CLI
通信闭环，最终由 Workflow Studio 展示和操作。

## 分层边界

### 1. 外部基础设施协议

`agent-cli-contract` 是外置协议边界，未来应能独立发包或作为 submodule 引入。
它只描述第三方 CLI/Agent 如何声明自己以及如何回传运行结果：

- `AgentCliCard`
- `RunReceipt`
- JSON Schema
- TypeScript types
- Python validator
- fixtures
- conformance smoke

它不能依赖 CBN daemon、workflow、artifact store、audit、MCP、A2A 或 ACP。

CBN 主仓只消费该协议，并负责映射：

- `AgentCliCard -> ToolManifest`
- `RunReceipt -> BridgeMessage + Artifact records + Audit/Event correlation`

当前主仓内先以 `external_protocols/agent-cli-contract` 作为可拆出的包边界承载该协议。
它包含 schema、TypeScript types、Python validator、fixtures 和 conformance smoke，
并通过独立 smoke 保证不 import CBN 模块。未来拿到独立仓库 URL 后可迁移为
submodule 或独立 npm/PyPI 包。

### 2. CBN 内部总线 Contract

CBN 内部总线 contract 由以下对象组成：

- `ToolManifest`：能力注册、执行模板、风险和 parser contract。
- `BridgeMessage`：能力输出和 CLI-CLI 通信 envelope。
- `Artifact`：stdout、stderr、parsed payload、文件或生成物证据。
- `Workflow selector`：从上游 BridgeMessage/Artifact 提取值并映射为下游 argv。

BridgeMessage 和 selector 已归位到 `cbn_core.message` 与 `cbn_core.selector`。
`cbn_protocol.envelope` 只保留兼容 re-export，避免打断现有调用。

### 3. 外部协议 Facade

`cbn_protocol` 只负责 MCP/A2A/ACP facade、descriptor export、smoke 和 conformance。
它不再是内部消息总线的所有者。外部协议面是导出层，不是 CBN runtime 的核心数据面。

## Workflow Studio MVP

Workflow Studio 是用户侧主界面，旧 `packages/dashboard` 保留为 maintainer console。

首版必须真实调用 daemon API：

- `/health`
- `/workflows`
- `/workflows?path=...`
- `/messages/contract?workflow_path=...`
- `/workflows/run`
- `/events`
- `/audit`
- `/artifacts`

界面结构：

- 左侧：daemon URL、session token、workflow path、dry-run/confirmed 输入流。
- 中间：LiteGraph workflow DAG，显示 task、needs、selector、capability 风险。
- 右侧：BridgeMessage/selector inspector、run result。
- 底部：event、audit、artifact evidence dock。

## Killer Demo 验收链

优先固化以下链路：

1. import CLI-Anything harness
2. generate manifest
3. run macrocli
4. parse payload
5. transform to mermaid
6. run mermaid
7. show artifact
8. show event/audit
9. export MCP/A2A smoke

优先复用：

- `workflows/cli-anything-macrocli-mermaid-routing.example.json`
- `manifests/cli-anything.macrocli.backends.json`
- `manifests/cbn.transform.macrocli-backends-to-mermaid.json`
- `manifests/cli-anything.mermaid.set-diagram.json`
- `cbn_tools/macrocli_backends_to_mermaid.py`

## 迭代顺序

1. BridgeMessage 归位到 `cbn_core`，保留旧 import path 兼容。
2. 定义并落地 `agent-cli-contract` 外置协议骨架。
3. 增加 CBN 侧 AgentCliCard/RunReceipt importer。
4. 新增 `packages/workflow-studio`，先做真实 daemon API 调用和 DAG 展示。
5. 把 killer demo 做成 Workflow Studio 首屏可运行路径。
6. 降低 CLI 注册成本：`cbn import command`、`cbn import cli-anything`、
   `cbn import skill`、`cbn import mcp`、`cbn record-parser-fixture`。
7. 拆分 `cbn_plugins/cli_anything.py` 为 market、probe、manifest_factory、
   repair、verification、onboarding。
8. 把 `cbn_adapter_agent` 抽象为未来 `cbn_agent` 节点模型。

## 当前 Slice

本 slice 只处理 BridgeMessage 归位：

- 新增 `cbn_core.message`。
- 新增 `cbn_core.selector`。
- runtime、CLI、API、workflow runner 使用 core import。
- `cbn_protocol.envelope` 保留 re-export 兼容。
- 不在同一提交中混入 Workflow Studio、协议外置仓库或 CLI-Anything 大拆分。

下一 slice 已建立 Agent CLI Contract 和 CBN 侧纯映射：

- `external_protocols/agent-cli-contract` 定义 `AgentCliCard` 与 `RunReceipt`。
- `cbn_core.agent_cli_contract.agent_cli_card_to_tool_manifests` 负责生成
  `ToolManifest` 字典。
- `cbn_core.agent_cli_contract.run_receipt_to_cbn_records` 负责生成
  `BridgeMessage`、artifact 记录形状、audit/event correlation 记录。
- 该 slice 仍不做 daemon 写入、不安装外部包、不改变 CLI/API 行为。

Workflow Studio slice 已新增 `packages/workflow-studio`：

- 技术栈为 Vue、TypeScript、Vite、LiteGraph。
- 首屏是 workflow workbench，不是按钮墙或 landing page。
- 左侧提供 daemon URL、session token、workflow path、dry-run、confirmed。
- 中间使用 LiteGraph 画布展示 workflow task DAG。
- 右侧展示 task、selector 和 run result。
- 底部 evidence dock 展示 events、audit、artifacts。
- 已接入 daemon API：`/health`、`/workflows`、`/workflows?path=...`、
  `/messages/contract?workflow_path=...`、`/workflows/run`、`/events`、
  `/audit`、`/artifacts`。
- 旧 `packages/dashboard` 保持 maintainer console，Studio 只保留一个小入口。

Killer Demo slice 已新增可运行证据束：

- 新增 `cbn_demo.killer.killer_demo_report`，聚合 manifest、workflow、BridgeMessage
  contract、workflow run、artifact/event/audit evidence、protocol export 和
  MCP/A2A/ACP smoke。
- daemon 新增 `GET /demo/killer` 与 `POST /demo/killer`，用于 Workflow Studio
  一键拉取演示链路证据。
- CLI 新增 `python -m cbn demo killer --run --dry-run`，用于本地验收同一份
  demo report。
- Workflow Studio 新增 `Demo` 按钮和 Killer Demo 阶段展示，复用当前 workflow path、
  dry-run、confirmed 输入流。
- 当前 demo 链路以 `workflows/cli-anything-macrocli-mermaid-routing.example.json`
  为默认入口，展示 macrocli -> parser payload -> Mermaid transform -> mermaid
  consumer 的 CLI-CLI BridgeMessage 通信链。

后续仍需继续推进的产品化收口：

- `cbn import command` 已有最小入口：默认生成并校验 `ToolManifest`，
  显式 `--write` 时写入 `runtime/manifests/<capability-id>.json` 或指定
  `--output`。它用于把普通 CLI 快速变成 CBN capability。
- `cbn import cli-anything` 已有兼容门面：复用
  `CliAnythingHub.onboard_harness`，默认只输出 evaluate/probe/adapt/install/verify
  阶段报告；`--write` 或 `--install` 需要 `--yes` 才执行副作用。
- `cbn record-parser-fixture` 已有最小入口：把一次 stdout/stderr 记录为
  `ParserFixture`，先用当前 `ParserRegistry` 自校验，显式 `--write` 才写入
  `parser_fixtures/<parser>.<case>.json` 或指定 `--output`。
- `cbn import mcp` 已有最小入口：读取 MCP tool descriptor 或 `tools/list`
  payload，生成现有 runtime 可执行的 `ToolManifest` 草案；当前通过用户提供的
  stdio adapter command 调用外部 MCP tool，并在 annotations 中保留 MCP schema
  与 provenance。
- `cbn import skill` 已有最小入口：读取 UTF-8 JSON/Markdown skill descriptor，
  结合用户提供的本地 runner command 生成现有 runtime 可执行的 `ToolManifest`
  草案，并在 annotations 中保留 skill id、source path、summary 和 version。
- `cbn_plugins/cli_anything.py` 已先 facade 后拆出
  `cbn_plugins.cli_anything_parts.manifest_factory`，集中管理
  CLI-Anything harness `ToolManifest` 生成、market metadata 映射、risk/network
  policy 推断和已验证 parser contract 保留；并拆出
  `cbn_plugins.cli_anything_parts.market`，集中管理 CLI-Anything market JSON
  解析、market record identity 和 capability collision 标记；拆出
  `cbn_plugins.cli_anything_parts.probe`，集中管理 requirements 解析、dependency
  probes、platform assessment 和 readiness summary；拆出
  `cbn_plugins.cli_anything_parts.repair`，集中管理 entrypoint repair 的候选包
  推断、install command 解析、entrypoint 诊断、wrapper 模板和 repair policy
  合并；拆出 `cbn_plugins.cli_anything_parts.verification`，集中管理 parser
  contract report、protocol verification summary、verification blockers、
  verification stages、parser fixture gate 和 smoke-suite command/status；拆出
  `cbn_plugins.cli_anything_parts.onboarding`，集中管理 onboarding 的 probe
  failure report、summary、stage results 和 next commands。旧
  `cbn_plugins.cli_anything` import path 继续兼容。
- 把 `cbn_adapter_agent` 抽象为可参与 workflow 的 Agent node，承载自然语言
  调度、初次设置引导和 BridgeMessage 收发。
- `cbn_agent` 已新增最小核心模型层：`AgentCard`、`AgentHarness`、
  `AgentSession`、`AgentTask`、`AgentBridgeMessage`。它复用
  `cbn_core.message.BridgeMessage` 作为内部总线输出，先不改变
  `cbn_adapter_agent` 现有行为，后续再逐步让 adapter agent 映射到这些稳定
  node records。
- `cbn_adapter_agent.nodes.build_adapter_agent_node_bundle` 已把现有
  Adapter Agent coordination roles 映射为 `cbn_agent` cards、harnesses、tasks、
  workflow nodes 和可校验的 AgentBridgeMessage；它是只读 bundle，不改变现有
  adapter agent CLI/API 行为。
- `python -m cbn_adapter_agent --node-bundle` 已新增只读 CLI 输出，便于 Workflow
  Studio、daemon 或外部程序一次性读取 Adapter Agent 的 node records 和总线
  BridgeMessage 证据。

## 验证策略

默认只跑针对性验证。除非人工主动指定，不跑全量单测；大型测试每小时最多运行一次。

本 slice 的验证重点：

- `python -m cbn health`
- `python -m cbn demo killer --run --dry-run --smoke-suite`
- `python -m unittest tests-unit.test_cli_anything_manifest_factory`
- `python -m unittest tests-unit.test_cli_anything_market`
- `python -m unittest tests-unit.test_cli_anything_probe`
- `python -m unittest tests-unit.test_cli_anything_repair`
- `python -m unittest tests-unit.test_cli_anything_verification`
- `python -m unittest tests-unit.test_cli_anything_onboarding`
- `python -m unittest tests-unit.test_cbn_agent_models`
- `python -m unittest tests-unit.test_adapter_agent_harness.AdapterAgentHarnessTests.test_adapter_agent_node_bundle_maps_roles_to_agent_contracts`
- `python -m unittest tests-unit.test_adapter_agent_harness.AdapterAgentHarnessTests.test_adapter_agent_node_bundle_cli_outputs_json`
- `python -m unittest tests-unit.test_killer_demo`
- `python -m unittest tests-unit.test_command_importer`
- `python -m unittest tests-unit.test_cli_imports`
- `python -m unittest tests-unit.test_parser_fixture_recorder`
- `python -m unittest tests-unit.test_mcp_importer`
- `python -m unittest tests-unit.test_skill_importer`
- `python -m unittest tests-unit.test_daemon_api.DaemonApiTests.test_killer_demo_route_returns_demo_report`
- `python -m unittest tests-unit.test_parser_protocol tests-unit.test_workflow_runner`
- `python -m unittest tests-unit.test_protocol_exports`
- `python -m unittest tests-unit.test_agent_cli_contract`
- `python external_protocols/agent-cli-contract/scripts/conformance_smoke.py`
- `node external_protocols/agent-cli-contract/scripts/check.mjs`
- `npm --workspace @cli-bridge/workflow-studio run check`
- `npm --workspace @cli-bridge/workflow-studio run build`
- `npm --workspace @cli-bridge/dashboard run check`
