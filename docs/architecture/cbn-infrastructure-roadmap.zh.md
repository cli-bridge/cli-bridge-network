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
该边界已补 `pyproject.toml` 和 `agent-cli-contract` Python console script，
支持 `agent-cli-contract validate card <file>` 与
`agent-cli-contract validate receipt <file>`；source-tree 模式也可通过
`python -m agent_cli_contract validate ...` 验证，不依赖 CBN runtime。
CBN 侧 `cbn_core.agent_cli_contract` 已在映射前消费该外置 validator；当前优先
加载已安装的 `agent_cli_contract` 包，未安装时降级到
`external_protocols/agent-cli-contract/python` 的 submodule/source-tree 边界。
`cbn_core.agent_cli_contract_package_boundary()` 与
`agent_cli_contract_package_health()` 已把该外置协议包边界提升为 core 级机器可读
报告：校验 package.json、pyproject、schemas、fixtures、TypeScript types、Python
validator、static check 和 conformance smoke 是否齐备，并扫描 Python/TS/scripts
源码确认不 import CBN runtime/protocol 模块。`NetworkConnectPackage.contracts.external`
同步携带 `package_health`，让第三方程序第一次读取 one-shot package 时即可判断
`agent-cli-contract` 是否仍是可拆包、可独立发包的干净边界。Workflow Studio
Connect 面板同步展示 package clean/attention、npm/Python 包名、source scan
数量、必需文件 present/missing 和 forbidden import offenders。

### 2. CBN 内部总线 Contract

CBN 内部总线 contract 由以下对象组成：

- `ToolManifest`：能力注册、执行模板、风险和 parser contract。
- `BridgeMessage`：能力输出和 CLI-CLI 通信 envelope。
- `Artifact`：stdout、stderr、parsed payload、文件或生成物证据。
- `Workflow selector`：从上游 BridgeMessage/Artifact 提取值并映射为下游 argv。

BridgeMessage 和 selector 已归位到 `cbn_core.message` 与 `cbn_core.selector`。
Bridge Contract 报告已归位到 `cbn_core.bridge_contract`，负责内部 ToolManifest、
BridgeMessage、Artifact 和 Workflow selector route readiness。`cbn_protocol.envelope`
与 `cbn_protocol.bridge_contract` 只保留兼容 re-export，避免打断现有调用。
`workflow_bridge_contract_report(...).contract.contracts` 已结构化暴露
`tool_manifest`、`bridge_message`、`artifact`、`workflow_selector` 四个内部总线
contract，旧的 rules 字段继续保留以兼容既有消费者。

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
   `cbn import agent-cli-card`、`cbn import skill`、`cbn import mcp`、
   `cbn record-parser-fixture`。
7. 拆分 `cbn_plugins/cli_anything.py` 为 market、probe、manifest_factory、
   repair、verification、onboarding。
8. 把 `cbn_adapter_agent` 抽象为未来 `cbn_agent` 节点模型。

## 当前 Slice

本 slice 只处理 BridgeMessage 归位：

- 新增 `cbn_core.message`。
- 新增 `cbn_core.selector`。
- runtime、CLI、API、workflow runner 使用 core import。
- `cbn_protocol.envelope` 保留 re-export 兼容。
- `cbn_protocol.bridge_contract` 保留 re-export 兼容；内部调用方改为
  `cbn_core.bridge_contract`，让 `cbn_protocol` 继续收敛为 MCP/A2A/ACP facade。
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
- 中间使用 LiteGraph 画布展示 workflow task DAG，并用端口连线表达
  `needs/argsFrom` 的 CLI-CLI BridgeMessage selector route。
- 右侧展示 task、selector、Bridge Contract 和 run result。
- 底部 evidence dock 展示 events、audit、artifacts。
- 已接入 daemon API：`/health`、`/workflows`、`/workflows?path=...`、
  `/messages/contract?workflow_path=...`、`/workflows/run`、`/events`、
  `/audit`、`/artifacts`。
- 已接入 `GET /adapter-agent/node-bundle`：左侧提供 Agent prompt，右侧展示
  Adapter Agent 的 cards、tasks、handoffs 和 BridgeMessage，LiteGraph 画布同时
  渲染 workflow task 与 agent workflow node，作为“自然语言 harness agent 参与
  CLI-CLI workflow”的首版展示面。
- Workflow Studio graph layer 已把 task `needs` 和 `argsFrom.task` 映射为
  LiteGraph 节点连接线，并在 consumer 节点文本中显示 selector，避免 demo 中只
  看到孤立节点而看不到 CLI-CLI 通信边。
- Workflow Studio 右侧已新增 Bridge Contract 摘要面板，直接展示
  `tool_manifest`、`bridge_message`、`artifact`、`workflow_selector` 四个内部总线
  contract 的 kind、owner、scope、required fields，并保留 raw contract JSON。
- Workflow Studio 支持 `daemonUrl`、`sessionToken`、`workflowPath`、
  `agentMessage` query 参数覆盖默认配置，便于在演示或多 daemon 端口并存时直接
  打开一条已配置好的 killer demo 链接。
- CLI 已新增 `python -m cbn network studio-link`，用于生成预配置 Workflow Studio
  URL；`NetworkConnectPackage.workflow_studio` 同步包含同一份
  `WorkflowStudioDemoLink`，外部程序拿到 one-shot connect package 后可直接打开
  带 daemon URL、workflow path、agent prompt、maintainer dashboard URL 和可选
  session token 的 Studio 页面。
- 旧 `packages/dashboard` 保持 maintainer console，Studio 只保留一个小入口。该入口
  默认打开 dashboard 独立服务 `http://127.0.0.1:5173`，也可通过 Studio URL 的
  `dashboardUrl` query 参数覆盖，避免把 maintainer console 的按钮面板并入用户侧
  Workflow Studio。

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
- Workflow Studio 新增 Killer Demo Evidence Summary，将 stage 进度、workflow
  status、route count、artifact count、event/audit count、smoke 和 bridge lab 状态
  汇总成可扫读的验收面板，同时保留原始 demo summary 供排错。
- Workflow Studio 新增 Protocol Export 摘要，将 demo report 内的 MCP workflow
  tools、A2A skills、ACP workflows、各协议 smoke pass/fail 和 wire facade 状态
  提升到可扫读区块，用于说明同一条 CLI-CLI workflow 可被外部协议 facade 接入。
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
- `cbn import agent-cli-card` 已有最小入口：读取外置
  `agent-cli-contract` 的 `AgentCliCard`，复用 CBN 侧纯映射生成一个或多个
  `ToolManifest` 草案；默认只返回验证报告，显式 `--write` 时写入
  `runtime/manifests/<capability-id>.json` 或指定 `--output-dir`。
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
- daemon 已新增 `GET /adapter-agent/node-bundle` 只读 API，复用同一份
  `AdapterAgentNodeBundle` 输出，便于 Workflow Studio 或外部 orchestrator 在不执行
  workflow、不写入状态的情况下读取 AgentCard、AgentTask、workflow node 和
  AgentBridgeMessage。
- Workflow Studio 已消费该只读 API：Agent prompt 会随 workflow path 一起请求
  node bundle，右侧 inspector 展示 AgentCard、handoff 与 BridgeMessage，画布下方
  同步渲染 agent workflow node，形成可展示的 Agent-as-Node MVP 入口。
- Workflow Studio 已新增只读 `Setup` 操作，调用 `POST /adapter-agent/tool-call-plan`
  展示 setup-secret、setup-command、workflow-capability、execution batch 和
  long-running loop checkpoints；它不执行登录、不写 secret，用于演示 API key、
  OAuth、authenticated session 等首跑场景下 Workflow Setup Agent 如何引导用户。
- `cbn_demo.network_connect.network_connect_package` 已新增只读
  `NetworkConnectPackage`：汇总 AgentCliCard/RunReceipt 外部 contract、
  ToolManifest/BridgeMessage/Artifact/selector 内部 contract、daemon endpoint
  catalog、workflow 摘要、MCP/A2A/ACP protocol export 摘要和 Agent node 摘要。
  `agent_node_bundle` 不是只有数量统计：它保留轻量结构化的 AgentSession、
  AgentCard、AgentHarness、AgentTask、AgentBridgeMessage 和 workflow node 摘要，
  让外部程序拿到 one-shot package 后可以识别可复用 harness agent 的角色、输入输出
  与 BridgeMessage 总线通道。
  其中 `contracts.internal.contracts` 直接复用
  `workflow_bridge_contract_report(...).contract.contracts` 的结构化段落，外部程序
  可一次性读取 ToolManifest、BridgeMessage、ArtifactRecord 和 WorkflowSelector
  的 kind、owner、scope、required fields 与 routing/validation 规则；旧的
  `contracts.internal.tool_manifest` 等字符串键保留为兼容摘要。
  daemon 已暴露 `GET /network/connect-package`，供外部程序一次性读取“如何接入
  CBN 网络”的最小包，不执行 workflow、不写入状态。
- Workflow Studio 已消费 `GET /network/connect-package`：左侧新增 `Connect`
  按钮，右侧新增 Connect Package 面板，展示 external contract、generated
  capability、daemon endpoint catalog、Bridge route、protocol export 和 agent
  card 摘要，作为“其他程序一次性接入网络”的产品化展示入口。该面板也会直接
  展示 one-shot package 内的结构化 internal bus contract sections，让 demo 现场
  能看到外部程序接入后会进入 ToolManifest、BridgeMessage、ArtifactRecord、
  WorkflowSelector 哪些内部对象边界；同时展示 one-shot package 内的 AgentSession、
  AgentCard、AgentHarness、AgentTask 和 AgentBridgeMessage 摘要，便于说明
  harness agent 如何作为 workflow node 进入总线。该面板也已消费
  `contracts.external.package_health`，把 `agent-cli-contract` 的独立包文件清单、
  package metadata 和 forbidden import scan 结果直接渲染出来，避免 demo 中只能
  口头说明外置协议边界。
- Connect Package 面板已把 `NetworkConnectPackage.workflow_studio` 提升为一等
  展示：可直接打开预配置 Workflow Studio demo link，并显示 session token 是否
  已包含、dry-run/live 模式和原始 `WorkflowStudioDemoLink` payload，便于外部程序
  拿到 one-shot package 后立即进入可视化验收界面。
- Workflow Studio 请求 connect package 时会把当前 Studio origin 作为
  `studio_url` 传给 daemon，同时把当前 session token 传给 link generator；因此
  one-shot demo link 不再隐式绑定默认 `127.0.0.1:5177`，可适配其他本地端口或远程
  预览环境。
- `NetworkConnectPackage` 已新增 `consumer_quickstart`：为外部程序提供机器可读
  first-call 指南，包括 required headers、open Studio URL、inspect workflow、
  inspect Bridge contract、inspect agent nodes、export MCP/A2A/ACP protocols、
  plan agent request、run workflow、events/audit/artifacts 入口和建议调用顺序。
  Workflow Studio Connect 面板同步展示 quickstart status、鉴权 header 状态和
  agent node、protocol export、plan/run endpoint。
- CLI 已新增 `python -m cbn network quickstart`，复用同一份
  `NetworkConnectPackage` 生成逻辑，但只输出 `consumer_quickstart`，让外部程序或
  demo 脚本能低噪声读取 first-call HTTP payload、headers 和推荐调用顺序。
- daemon 已新增 `GET /network/quickstart`，同样只返回 `consumer_quickstart`。
  该路由复用 connect package 生成逻辑，并支持从 `X-CBN-Session` header 推导
  required headers 与预配置 Studio link，便于外部程序按标准鉴权 header 直接读取
  first-call payload。
- `consumer_quickstart` 已新增 `requests[]` 可执行请求计划：按 health、inspect
  workflow、inspect Bridge contract、inspect agent nodes、export MCP/A2A/ACP
  protocols、plan agent request、run workflow、events/audit/artifacts 顺序展开
  method、url、headers 和 POST json，外部程序无需再自行从 entrypoints 拼装首批
  HTTP 调用。
- Workflow Studio Connect 面板已将 `requests[]` 渲染为 first-call request
  sequence，每行展示 method、request id 和 URL；演示时可以直接看到外部程序接入
  CBN 网络所需的首批 HTTP 调用顺序，而不必展开原始 JSON。
- `requests[]` 每项已带 `curl` 示例，覆盖 header、method 和 POST JSON body；
  Workflow Studio 同步展示该命令，方便 demo 或外部程序作者直接复制首批调用。
- `consumer_quickstart.curl_script` 已把全部 first-call curl 按顺序合并为一段
  `set -e` 脚本，Studio Connect 面板提供多行预览，用于演示或手工 smoke。
- `consumer_quickstart.powershell_script` 已提供同一组 first-call 的 Windows/
  PowerShell `Invoke-RestMethod` 脚本，包含统一 headers 和 POST JSON body；Studio
  Connect 面板同步预览，便于在当前 Windows 开发环境直接 smoke。
- `consumer_quickstart.sdk_snippets` 已新增可复制 SDK handoff：提供 Python
  stdlib consumer 和 TypeScript fetch consumer 两份代码片段，固定 health ->
  natural-language harness plan -> workflow run -> events/audit/artifacts 的最小接入
  顺序，并显式标记 dry-run、confirmed、requires-daemon 等 safety 信息。Workflow
  Studio Connect 面板同步展示 snippet 数、语言/runtime、request ids 和复制按钮，
  让其他程序不只拿到 HTTP JSON，也能直接嵌入一段最小可运行 client。
- Workflow Studio Connect 面板已为 cURL 与 PowerShell 脚本提供复制按钮，降低
  demo 或第三方接入时从可视化界面拷贝 first-call smoke 脚本的操作成本。
- `python -m cbn network quickstart --output curl|powershell` 已支持直接输出可执行
  first-call 脚本；第三方接入、demo 和本地 smoke 不再需要先解析 JSON 字段。
- `NetworkConnectPackage.acceptance` / `consumer_quickstart.acceptance` 已新增
  `NetworkConnectionAcceptance` 机器可读验收清单，覆盖 health、workflow inspect、
  Bridge contract、agent node bundle、MCP/A2A/ACP protocol exports、自然语言
  harness plan、workflow run、events/audit/artifacts 的期望证据；`python -m cbn
  network quickstart --output acceptance` 可直接输出该 checklist，Workflow Studio
  Connect 面板同步展示每个 check。
- `NetworkConnectionAcceptance` 的 events、audit、artifacts checks 已从“端点返回
  JSON 数组”提升为“workflow run 之后至少返回 1 条 evidence”，让 one-shot
  `network verify` 能证明 demo 链路不只完成调用，还能产生可展示的 runtime
  event、audit 和 artifact 证据。
- Workflow Studio 的 browser-side `Verify` 已同步支持 `json.count_min` /
  `json.length_min` 和 `json.<field>_count_min`，因此前端 replay quickstart 与
  daemon-side `Daemon Verify` 对同一份 `NetworkConnectionAcceptance` 使用一致的
  evidence 判定语义。
- Workflow Studio Connect 面板已新增 `Verify` 操作，会按 quickstart request
  sequence 真实调用 daemon 并用 `NetworkConnectionAcceptance` 的 expect 字段判定
  pass/fail/skipped；这让 demo 现场可以直接证明外部程序一键接入 CBN 网络后的
  最小验收结果，而不是只展示静态 checklist。
- CLI 已新增 `python -m cbn network verify`，复用同一份 quickstart + acceptance
  contract 对 live daemon 发起 HTTP 调用并输出 `NetworkConnectionAcceptanceReport`；
  该报告包含每个 check 的 http status、expect/actual evidence 和 pass/fail/skipped
  汇总，供第三方程序或 CI smoke 直接复用。
- daemon 已新增 `POST /network/verify`，外部程序可不依赖本地 Python CLI，直接用
  HTTP 触发同一份 live acceptance report；`NetworkConnectPackage.daemon_endpoints`
  也会暴露该验收入口。
- `NetworkConnectPackage.next_commands`、`demo_readiness.next_commands` 和
  `NetworkConnectionAcceptanceReport.next_commands` 已继承当前 `base_url` 与可选
  `session_token`，第三方程序拿到 one-shot package 后可以直接复用建议命令，不必
  再手工补 daemon URL 或鉴权 token。
- Workflow Studio Connect 面板已把 top-level `next_commands` 与
  `demo_readiness.next_commands` 合并去重后渲染为可复制命令列表，让 demo 或
  第三方接入现场不必展开 raw JSON 才能继续执行下一步。
- Workflow Studio Connect 面板已新增 `Daemon Verify` 操作，直接调用
  `POST /network/verify` 并展示 `NetworkConnectionAcceptanceReport` 摘要，同时复用
  report results 刷新 check 列表；现有 `Verify` 保留为 browser-side quickstart
  replay，用于区分前端可达性和 daemon-side 一键验收。
- CLI 已新增 `python -m cbn network connect-package` 只读入口，输出同一份
  `NetworkConnectPackage`。外部程序无需先接 daemon/WebUI，也能一次性读取
  AgentCliCard/RunReceipt contract、daemon endpoint catalog、protocol facade 和
  Agent-as-Node 摘要。
- `cbn_adapter_agent.workflow_request.build_agent_workflow_request_plan` 已新增
  确定性自然语言请求入口：输入 agent message + workflow path，输出
  `AdapterAgentWorkflowRequestPlan`，包含 workflow run payload、CLI/HTTP 调用方式、
  CLI-CLI BridgeMessage selector routes、可复用 `NaturalLanguageWorkflowHarness`
  摘要和 `agent.workflow.request.plan` BridgeMessage。它不执行 workflow、不写文件，
  用于把“harness agent 用自然语言调用 CLI-CLI workflow”产品化成可展示、可复用
  的契约。
- daemon 已新增 `POST /adapter-agent/workflow-request-plan`，Workflow Studio 已新增
  `Plan` 按钮和 Agent Workflow Plan 面板，用同一份 agent prompt 生成可扫读的
  workflow invocation plan、Bridge route、run command 和 BridgeMessage 证据。
- `NetworkConnectPackage` 已纳入 `agent_workflow_request` 摘要，并在 daemon endpoint
  catalog 中暴露 `POST /adapter-agent/workflow-request-plan`。外部程序现在只读取一次
  connect package，就能同时获得 AgentCliCard/RunReceipt 外部协议、CBN 内部
  BridgeMessage/selector contract、MCP/A2A/ACP facade、Agent node bundle、自然语言
  workflow request plan 和可直接调用的 `/workflows/run` payload。
- `NetworkConnectPackage.agent_workflow_request` 已从“仅摘要”扩展为可复用 harness
  invocation contract：保留 natural-language request binding、intent、run CLI/HTTP
  payload、BridgeMessage argsFrom routes、compact `agent.workflow.request.plan`
  BridgeMessage 和 next commands。第三方程序无需额外调用 adapter-agent plan endpoint，
  读取一次 one-shot package 即可知道 harness agent 如何把自然语言请求绑定到
  CLI-CLI workflow、如何 POST `/workflows/run`、以及 CLI-CLI 间的 selector 路由如何
  通过 BridgeMessage 传递。Workflow Studio Connect 面板同步展示 harness kind、
  binding、run endpoint、BridgeMessage channel 和前几条 selector route。
- `cbn network connect-package|quickstart|verify`、daemon `/network/*` 和 Python API
  已统一默认 agent prompt，默认语义同时包含 run、reusable CLI-CLI harness agent 和
  external program connect，避免 CLI 与 HTTP 入口生成不同 intent。
- `NetworkConnectPackage.registration_surface` 已新增只读 CLI 注册入口目录：把
  `cbn import command`、`cbn import cli-anything`、`cbn import agent-cli-card`、
  `cbn import mcp`、`cbn import skill` 和 `cbn record-parser-fixture` 的 entrypoint、
  accepts、produces、write/confirm gate、默认无副作用策略和 help commands 放进
  one-shot package。外部程序拿到 connect package 后，不只知道如何调用当前
  workflow，也能知道如何把更多普通 CLI、CLI-Anything harness、MCP tool、skill 或
  parser fixture 纳入 CBN 网络。Workflow Studio Connect 面板同步展示 importer 数量、
  dry-run import policy 和前几条注册入口。
- `cbn_core.import_catalog.cli_registration_surface()` 已成为 CLI 注册入口目录的单一
  事实源；`NetworkConnectPackage.registration_surface` 和新增
  `python -m cbn import catalog` 均复用它。外部程序现在无需生成完整 connect
  package，也能只读获取 importer id、entrypoint、help command、accepts/produces、
  write/confirm gate、dry-run-first policy 和示例命令，降低“把下一个 CLI 接入 CBN”
  的发现成本。
- `NetworkConnectPackage.contracts.external.package_boundary` 已新增
  `ExternalProtocolPackageBoundary`：把 `agent-cli-contract` 的 npm/Python 包名、
  schema 路径、TypeScript types、Python validator、fixtures、conformance smoke
  command、standalone dependency boundary 和 CBN 侧映射责任一起暴露。这样第三方
  第一次读取 one-shot package 时，可以明确区分外部协议包只负责
  AgentCliCard/RunReceipt，CBN 主仓负责 ToolManifest、BridgeMessage、artifact、
  audit/event correlation 和 MCP/A2A/ACP facade。
- `NetworkConnectPackage.demo_readiness` 已新增只读 Killer Demo 摘要：不执行
  workflow、不写状态，只暴露 CLI-Anything -> macrocli -> parser -> Mermaid ->
  artifact/event/audit -> MCP/A2A/ACP smoke 的 stage 列表、required capabilities、
  evidence contracts、`/demo/killer` endpoint、Workflow Studio link 和下一步命令。
  Workflow Studio Connect 面板同步展示 demo readiness、stage count 和 killer demo
  endpoint，并把 7 个 demo readiness stages 渲染成可扫读链路，让其他程序第一次
  读取 one-shot package 时就能理解最终 demo 呈现链路。
- `NetworkConnectPackage.demo_playbook` 已新增 `KillerMvpDemoPlaybook`：把打开
  Workflow Studio、检查 one-shot contract、运行 Demo、执行 Daemon Verify、查看
  MCP/A2A/ACP facade、注册下一个 CLI 这 6 个演示动作编排成机器可读 step list，
  并附带 success criteria 与 next commands。Workflow Studio Connect 面板同步展示
  playbook 状态、step 数和前几步，便于现场演示不再依赖口头步骤说明。
- `NetworkConnectPackage.setup_guidance` 已新增只读首跑设置摘要：复用
  `AdapterAgentToolCallPlan`，暴露 setup-secret、setup-command、workflow-capability、
  execution batch、loop checkpoint、user gate 和 secret count，但不执行工具、不写入
  secret、不输出 secret value 或原始 argv。外部程序读取 one-shot package 后，不必先
  打开 WebUI，就能判断 workflow 是否需要 API key、OAuth/login、Local REST key 或
  其他人工 setup；Workflow Studio Connect 面板同步展示该 setup 状态、用户门槛、
  secret 数量和安全标记。

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
- `python -m unittest tests-unit.test_adapter_agent_harness.AdapterAgentHarnessTests.test_adapter_agent_workflow_request_plan_binds_prompt_to_cli_cli_workflow`
- `python -m unittest tests-unit.test_adapter_agent_harness.AdapterAgentHarnessTests.test_adapter_agent_workflow_request_plan_cli_outputs_json`
- `python -m unittest tests-unit.test_daemon_api.DaemonApiTests.test_adapter_agent_node_bundle_route_returns_agent_nodes`
- `python -m unittest tests-unit.test_daemon_api.DaemonApiTests.test_adapter_agent_workflow_request_plan_route_returns_reusable_invocation`
- `python -m unittest tests-unit.test_daemon_api.DaemonApiTests.test_network_connect_package_route_returns_one_shot_contract`
- `python -m unittest tests-unit.test_network_connect`
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
