# CLI Bridge Network

简体中文 | [English](README.en.md)

CLI Bridge Network（CBN）是一个本地优先的能力网络，用来把命令行工具、解析器、MCP 服务、Agent CLI 合约和自动化工作流统一成可声明、可审计、可路由的能力层。

它的目标不是替代现有 CLI，而是为这些 CLI 补上一层稳定的工程骨架：能力清单、策略审批、执行器、结构化消息、产物、事件、审计日志、工作流编排，以及面向不同协议或前端的适配出口。

> 当前项目处于 MVP / 骨架快速迭代阶段。仓库中已经包含可运行的 Python CLI、本地 HTTP daemon、Workflow Studio 前端、Agent CLI Contract 边界、TypeScript package 边界和 Rust workspace 骨架。协议相关能力目前以描述符导出、检查、烟测和适配边界为主，不应理解为已经实现完整 wire-compatible 的 MCP / A2A / ACP 服务器。

## 目录

- [项目定位](#项目定位)
- [适用场景](#适用场景)
- [核心流程](#核心流程)
- [功能概览](#功能概览)
- [仓库结构](#仓库结构)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始](#快速开始)
- [CLI 使用说明](#cli-使用说明)
- [本地 Daemon 与 API](#本地-daemon-与-api)
- [Workflow Studio 与桌面入口](#workflow-studio-与桌面入口)
- [Manifest 与能力注册](#manifest-与能力注册)
- [策略、审批与执行安全](#策略审批与执行安全)
- [解析器、消息、产物、事件与审计](#解析器消息产物事件与审计)
- [Workflow 工作流](#workflow-工作流)
- [协议与 Agent CLI Contract](#协议与-agent-cli-contract)
- [插件与外部适配](#插件与外部适配)
- [配置与运行时数据](#配置与运行时数据)
- [开发与测试](#开发与测试)
- [常见问题](#常见问题)
- [许可证](#许可证)

## 项目定位

CBN 关注的是“把已经存在的工具变成可靠的本地能力网络”。

很多自动化项目最初都是一堆脚本、命令、批处理、HTTP 小服务、浏览器自动化、模型工具、下载器、解析器和临时 glue code。它们能跑，但很难回答这些问题：

- 这个工具的输入参数、输出结构和风险级别是什么？
- 运行前能不能先 dry-run？
- 哪些操作需要用户确认？
- 运行结果能不能被下一个步骤稳定引用？
- 错误、产物、事件和审计记录在哪里？
- 这个能力能不能被前端、MCP、Agent 或其他协议复用？
- 本地临时脚本能不能逐步升级成可维护的能力包？

CLI Bridge Network 的设计就是围绕这些问题展开。它把一个工具抽象成声明式能力，再通过受控执行、解析、产物归档、事件发布、审计记录和工作流路由，把本地工具串成可追踪的执行网络。

## 适用场景

CBN 比较适合以下场景：

- 你有一批本地 CLI、脚本、批处理或小工具，希望统一注册、调用和审计。
- 你希望在真正执行前先看到命令、参数、风险级别和 dry-run 结果。
- 你希望把 CLI 输出转换为结构化消息，而不是让后续流程解析一坨文本。
- 你希望把多个 CLI 串成 DAG 工作流，并用上游输出填充下游参数。
- 你希望为本地工具提供一个前端操作台，而不是只靠终端记命令。
- 你希望在 MCP、A2A、ACP、Agent CLI Contract 等协议之间保留统一的内部模型。
- 你正在做本地 agent / tool network / workflow runtime / protocol adapter 的原型，需要一个标准骨架。

CBN 不适合被理解为：

- 一个远程 SaaS 平台。
- 一个通用 shell 托管器。
- 一个已经完成所有外部协议 wire compatibility 的生产服务器。
- 一个绕过权限、审批或用户确认的自动执行器。

## 核心流程

CBN 的核心链路可以概括为：

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

对应到实际目录：

- `manifests/` 声明能力。
- `cbn_runtime/` 组装运行时上下文。
- `cbn_execution/` 负责受控执行、策略判断、解析和产物写入。
- `cbn_policy/` 与 `cbn_approval/` 处理风险和审批。
- `cbn_parsers/` 处理 CLI 输出解析。
- `cbn_artifacts/`、`cbn_events/`、`cbn_audit/` 记录产物、事件与审计日志。
- `cbn_workflow/` 把能力组织成可执行 DAG。
- `api_server/` 暴露本地 HTTP API。
- `frontend/` 提供 Workflow Studio / Electron 前端。
- `cbn_protocol/`、`external_protocols/`、`packages/`、`crates/` 承载协议和跨语言边界。

## 功能概览

| 能力 | 当前状态 | 说明 |
| --- | --- | --- |
| 能力注册 | 可用 | 从 `manifests/` 和本地 runtime overlay 加载 ToolManifest。 |
| CLI 调用 | 可用 | 通过 `python -m cbn call <capability>` 调用能力，支持 dry-run。 |
| 策略与审批 | 可用 | 高风险、外部副作用或需确认操作可以进入审批流。 |
| 输出解析 | 可用 | parser 将 stdout / stderr 转为结构化 `BridgeMessage`。 |
| 产物管理 | 可用 | 调用结果、解析输出和相关文件可进入 artifact store。 |
| 事件总线 | 可用 | 运行过程可发布事件，便于前端和自动化消费。 |
| 审计日志 | 可用 | 能力调用、审批和工作流执行会留下审计记录。 |
| Workflow DAG | 可用 | 使用 `needs` 和 `argsFrom` 连接多步任务。 |
| 本地 daemon | 可用 | 标准库 HTTP 服务，提供 registry、workflow、artifact、approval 等 API。 |
| Workflow Studio | 可用 | Vue + Vite + Electron 前端，用于图形化管理和执行工作流。 |
| Agent CLI Contract | 可用边界 | 支持 `AgentCliCard` / `RunReceipt` 的合约、fixture 和 smoke 脚本。 |
| MCP / A2A / ACP | MVP 边界 | 提供描述符导出、检查、矩阵和 smoke 入口；不是完整协议服务器。 |
| CLI-Anything 插件 | 可用边界 | 提供外部 CLI hub / adapter 的注册、preflight、plan 和安装边界。 |
| TypeScript packages | 骨架 | `packages/*` 定义跨语言核心、网络、MCP 和 adapter 包边界。 |
| Rust crates | 骨架 | `crates/*` 是未来 Rust 原生运行时或组件边界。 |

## 仓库结构

| 路径 | 作用 |
| --- | --- |
| `cbn/` | Python CLI 入口，包含命令解析和各子命令分发。 |
| `cbn_core/` | 核心类型、消息模型和共享协议对象。 |
| `cbn_runtime/` | 运行时上下文装配，集中创建 registry、executor、workflow runner、stores 和 plugin runner。 |
| `cbn_execution/` | 能力执行器，处理 manifest、策略、审批、stdio / PTY / in-process / MCP 调用、parser 和 artifact。 |
| `cbn_config/` | 路径、运行时配置和本地目录约定。 |
| `cbn_policy/` | 风险策略、执行前检查和审批判定。 |
| `cbn_approval/` | 审批请求、审批状态和本地审批存储。 |
| `cbn_parsers/` | 输出解析器注册、parser 运行和 fixture 录制。 |
| `cbn_artifacts/` | 产物存储、产物元数据和可追溯引用。 |
| `cbn_events/` | 事件总线和事件读取。 |
| `cbn_audit/` | 审计日志写入和查询。 |
| `cbn_workflow/` | 工作流验证、拓扑排序、参数路由、执行和结果汇总。 |
| `cbn_protocol/` | MCP / A2A / ACP 等协议描述符与适配边界。 |
| `cbn_plugins/` | 插件操作运行器和外部插件边界。 |
| `cbn_tools/` | 内置工具辅助代码。 |
| `api_server/` | 本地 HTTP daemon，提供 registry、workflow、artifact、approval、protocol 等 API。 |
| `frontend/` | Vue 3 + Vite + Electron 的 Workflow Studio 前端。 |
| `packages/` | TypeScript workspace packages，保留跨语言 SDK / MCP / adapter 边界。 |
| `crates/` | Rust workspace skeleton，保留未来 Rust 组件边界。 |
| `external_protocols/agent-cli-contract/` | Agent CLI Contract 合约、fixture、Python package 和 smoke 脚本。 |
| `manifests/` | 默认能力清单。 |
| `parser_fixtures/` | parser 测试和录制 fixture。 |
| `workflows/` | 示例工作流。 |
| `custom_adapters/` | 本地自定义 adapter 扩展点，类似 ComfyUI `custom_nodes` 的组织方式。 |
| `external_plugins/` | 外部插件安装位置，通常不提交到 Git。 |
| `runtime/` | 本地运行时数据、产物、事件、审计和审批状态，通常不提交到 Git。 |
| `tests-unit/` | Python 单元测试。 |
| `main.py`、`server.py`、`nodes.py`、`protocol.py` | 兼容或演示入口，主要 CLI 入口仍建议使用 `python -m cbn` 或安装后的 `cbn`。 |

## 环境要求

### 必需环境

| 组件 | 要求 |
| --- | --- |
| Python | `>= 3.10` |
| pip | 用于安装 editable package 和可选依赖 |
| Git | 示例 manifest 中包含 Git 能力，部分 smoke 也依赖 Git |

### 可选环境

| 组件 | 用途 |
| --- | --- |
| Node.js / npm | 运行 `frontend/`、Electron 和 TypeScript package 检查。 |
| Rust toolchain | 检查 `crates/*` workspace。 |
| `pywinpty` | Windows 上需要 PTY 模式时安装 `.[pty]` 可选依赖。 |
| `ffprobe` | 使用媒体探测 manifest 时需要。 |
| 外部 CLI / 插件 | `cli-anything`、第三方工具、MCP 服务等能力只在对应工具已安装时可用。 |

### Windows 编码建议

仓库约定读写统一使用 UTF-8。Windows PowerShell 中建议先设置：

```powershell
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

## 安装

### 1. 克隆仓库

```powershell
git clone https://github.com/cli-bridge/cli-bridge-network.git
cd cli-bridge-network
```

如果你是在本地开发分支中使用，也可以直接进入当前 checkout。

### 2. 创建 Python 虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
```

### 3. 安装 Python 包

推荐使用 editable install：

```powershell
python -m pip install -e .
```

安装后会提供 `cbn` console script：

```powershell
cbn --version
cbn health
```

也可以不依赖 console script，直接从源码运行：

```powershell
python -m cbn --version
python -m cbn health
```

### 4. 安装可选 PTY 依赖

Windows 上如果需要 PTY 执行模式：

```powershell
python -m pip install -e ".[pty]"
```

### 5. requirements.txt

当前 `requirements.txt` 有意保持为空，表示运行时依赖暂时优先使用 Python 标准库和 `pyproject.toml` 中定义的包元数据。

如果后续项目加入 runtime dependency，可以使用：

```powershell
python -m pip install -r requirements.txt
```

### 6. 安装前端依赖

```powershell
npm install
npm --workspace frontend run check
```

### 7. 检查 Rust workspace

Rust 部分目前是 workspace skeleton。如果你安装了 Rust toolchain，可以运行：

```powershell
cargo check --workspace
```

## 快速开始

### 查看版本和健康状态

```powershell
python -m cbn --version
python -m cbn health
```

示例健康状态会返回 JSON，包含项目名、版本、状态和 daemon token 配置摘要。

### 查看可用能力

```powershell
python -m cbn registry list
```

registry 会从默认 manifest 和本地 runtime overlay 加载能力。不同机器上输出可能不同，因为外部插件、本地 manifest、runtime overlay 和已安装 CLI 会影响最终能力列表。

### dry-run 调用能力

```powershell
python -m cbn call git.version --dry-run
```

dry-run 会构造命令、生成结构化消息和审计记录，但不会真正执行外部副作用型命令。建议所有新 manifest 和新工作流先用 dry-run 验证。

### 查看示例工作流

```powershell
python -m cbn workflow list
python -m cbn workflow inspect workflows\example.json
```

### 启动本地 daemon

```powershell
python -m cbn daemon routes
python -m cbn daemon serve --host 127.0.0.1 --port 8787
```

### 启动 Workflow Studio

```powershell
npm install
npm run app:dev
```

Windows 上也可以使用：

```powershell
.\start-electron.bat
```

## CLI 使用说明

CBN 的主要入口是：

```powershell
python -m cbn <command> [options]
```

如果已执行 `python -m pip install -e .`，也可以使用：

```powershell
cbn <command> [options]
```

### 基础命令

| 命令 | 作用 |
| --- | --- |
| `python -m cbn --help` | 查看顶层帮助。 |
| `python -m cbn --version` | 查看 CBN 版本。 |
| `python -m cbn health` | 检查本地运行时健康状态。 |
| `python -m cbn paths` | 查看项目路径和运行时路径。 |
| `python -m cbn nodes` | 查看节点相关信息。 |

### Registry 与能力调用

| 命令 | 作用 |
| --- | --- |
| `python -m cbn registry list` | 列出已加载能力。 |
| `python -m cbn registry search <keyword>` | 搜索能力。 |
| `python -m cbn registry inspect <capability-id>` | 查看某个能力的 manifest。 |
| `python -m cbn registry validate` | 校验 manifest。 |
| `python -m cbn call <capability-id> --dry-run` | 以 dry-run 模式调用能力。 |
| `python -m cbn call <capability-id> --arg name=value` | 传入参数调用能力。 |

示例：

```powershell
python -m cbn registry inspect git.version
python -m cbn call git.version --dry-run
```

### 审计、事件与产物

| 命令 | 作用 |
| --- | --- |
| `python -m cbn audit tail` | 查看最近审计记录。 |
| `python -m cbn event tail` | 查看最近事件。 |
| `python -m cbn artifact list` | 列出产物。 |
| `python -m cbn artifact inspect <artifact-id>` | 查看产物详情。 |

### Parser 与 fixture

| 命令 | 作用 |
| --- | --- |
| `python -m cbn parser list` | 列出 parser。 |
| `python -m cbn parser inspect <parser-id>` | 查看 parser。 |
| `python -m cbn record-parser-fixture ...` | 录制 parser fixture。 |

### Workflow

| 命令 | 作用 |
| --- | --- |
| `python -m cbn workflow list` | 列出工作流 JSON。 |
| `python -m cbn workflow inspect <workflow.json>` | 查看工作流结构。 |
| `python -m cbn workflow validate <workflow.json>` | 校验工作流。 |
| `python -m cbn workflow plan <workflow.json>` | 输出执行计划。 |
| `python -m cbn workflow run <workflow.json> --dry-run` | dry-run 执行工作流。 |
| `python -m cbn workflow run <workflow.json>` | 执行工作流。 |

示例：

```powershell
python -m cbn workflow inspect workflows\example.json
python -m cbn workflow run workflows\example.json --dry-run
```

### Protocol

| 命令 | 作用 |
| --- | --- |
| `python -m cbn protocol list` | 查看协议描述符。 |
| `python -m cbn protocol export <protocol>` | 导出协议描述。 |
| `python -m cbn protocol check <protocol>` | 检查协议边界。 |
| `python -m cbn protocol matrix` | 查看协议能力矩阵。 |
| `python -m cbn protocol readiness` | 查看协议就绪度。 |

当前协议命令应理解为 MVP 描述符、导出、检查和 smoke 边界。`python -m cbn protocol list` 会标注 wire compatibility 状态。

### Import 与插件

| 命令 | 作用 |
| --- | --- |
| `python -m cbn import ...` | 从 command、MCP、skill、Agent CLI Card 或 CLI-Anything 等来源导入能力。 |
| `python -m cbn plugin list` | 列出插件。 |
| `python -m cbn plugin info <plugin>` | 查看插件信息。 |
| `python -m cbn plugin plan <plugin>` | 查看插件计划。 |
| `python -m cbn plugin preflight <plugin>` | 执行插件 preflight。 |

### Daemon

| 命令 | 作用 |
| --- | --- |
| `python -m cbn daemon routes` | 列出本地 API 路由。 |
| `python -m cbn daemon serve --host 127.0.0.1 --port 8787` | 启动本地 HTTP daemon。 |

### Network

| 命令 | 作用 |
| --- | --- |
| `python -m cbn network ...` | 访问 network package、quickstart、entry profile、consumer manifest、acceptance、verify、studio-link 等网络层辅助命令。 |

## 本地 Daemon 与 API

CBN daemon 是一个本地优先的标准库 HTTP 服务，默认用于连接 CLI、Workflow Studio、审批面板、产物查询和协议边界。

查看路由：

```powershell
python -m cbn daemon routes
```

启动服务：

```powershell
python -m cbn daemon serve --host 127.0.0.1 --port 8787
```

常见本地地址：

| 服务 | 默认地址 |
| --- | --- |
| CBN daemon | `http://127.0.0.1:8787` |
| Workflow Studio | `http://127.0.0.1:5177` |
| Dashboard / Vite dev | `http://127.0.0.1:5173` |

daemon 覆盖的 API 类别包括：

- registry 与能力查询。
- capability 调用与 dry-run。
- workflow 列表、检查、执行和运行状态。
- artifact、event、audit 查询。
- approval 创建、查看、批准、拒绝。
- parser、protocol、plugin、network 和 MCP ingress 边界。
- thread、favorite、card 等本地 UI 状态。

### Daemon session token

本地 daemon 支持 session token 配置：

| 环境变量 | 作用 |
| --- | --- |
| `CBN_DAEMON_SESSION_TOKEN` | 指定 daemon token。 |
| `CBN_DAEMON_REQUIRE_SESSION_TOKEN` | 是否强制要求 token。 |

客户端可以通过以下方式传入 token：

- `X-CBN-Session: <token>`
- `Authorization: Bearer <token>`

本地开发时，loopback host 可以不强制 token；非本地或更严格环境建议开启 token。

## Workflow Studio 与桌面入口

`frontend/` 是 CBN 的图形化工作台，技术栈为 Vue 3、Vite、LiteGraph 和 Electron。

常用命令：

```powershell
npm install
npm --workspace frontend run check
npm --workspace frontend run app:dev
```

也可以从仓库根目录运行：

```powershell
npm run app:dev
```

Windows 桌面入口：

```powershell
.\start-electron.bat
```

`start-electron.bat` 会设置 UTF-8 代码页和 daemon 地址相关环境变量，然后启动 Electron dev workflow。

Workflow Studio 适合做这些事情：

- 浏览能力 registry。
- 组装工作流节点。
- 查看节点执行状态。
- 观察事件、产物和审计信息。
- 处理需要用户确认的审批项。
- 作为本地 CLI 能力网络的可视化入口。

## Manifest 与能力注册

CBN 通过 ToolManifest 描述能力。一个 manifest 通常需要说明：

- capability id。
- 名称和描述。
- 参数 schema。
- 执行方式。
- 输出 parser。
- 风险等级。
- 是否允许 dry-run。
- 是否需要审批。
- 产物和消息映射。

默认 manifest 位于：

```text
manifests/
```

运行时还可能加载本地 overlay manifest。overlay 适合放置机器相关、本地实验或不适合提交的能力声明。

常用 registry 命令：

```powershell
python -m cbn registry list
python -m cbn registry inspect git.version
python -m cbn registry validate
```

建议新增能力时遵循以下流程：

1. 先写最小 manifest。
2. 使用 `registry validate` 校验。
3. 使用 `call <id> --dry-run` 检查命令构造。
4. 添加 parser 或使用已有 parser。
5. 录制 parser fixture。
6. 再接入 workflow 或前端。

## 策略、审批与执行安全

CBN 的执行不是简单地把字符串交给 shell。执行路径会经过：

```text
manifest lookup -> policy decision -> approval check -> execution -> parse -> artifact -> audit
```

安全相关设计：

- 默认鼓励 dry-run-first。
- 高风险能力可以被策略阻止。
- 需要用户确认的能力会创建 approval request。
- 外部副作用型操作可以被要求显式批准。
- 执行结果会写入审计日志。
- 输出会通过 parser 转为结构化消息，减少下游误解析。
- 本地 `.env`、runtime 数据和外部插件目录不应提交到 Git。

审批相关命令可通过查看帮助获得：

```powershell
python -m cbn approvals --help
```

## 解析器、消息、产物、事件与审计

CBN 的重要目标之一是让 CLI 输出不再只是不可追踪的文本。

### BridgeMessage

`BridgeMessage` 是 CBN 内部用于传递执行结果的结构化消息。它通常包含：

- 调用信息。
- 状态。
- stdout / stderr 摘要。
- parser 输出。
- artifact 引用。
- 错误信息。
- 可被 workflow `argsFrom` 引用的字段。

### Artifact

artifact 用于保存运行结果和可追溯产物，例如：

- 结构化 JSON 输出。
- parser 结果。
- 命令执行摘要。
- 工作流中间结果。
- 外部工具生成的文件引用。

### Event

event 用于前端和自动化订阅执行过程，例如：

- capability started。
- capability completed。
- workflow task completed。
- approval requested。
- artifact created。

### Audit

audit log 用于回答“什么时候、谁、用什么参数、调用了什么能力、结果是什么”。

常用命令：

```powershell
python -m cbn audit tail
python -m cbn event tail
python -m cbn artifact list
```

## Workflow 工作流

Workflow 使用 JSON 描述 DAG。每个 task 可以调用一个 capability，并通过 `needs` 声明依赖，通过 `argsFrom` 从上游 `BridgeMessage` 中提取参数。

示例工作流位于：

```text
workflows/
```

常用命令：

```powershell
python -m cbn workflow list
python -m cbn workflow inspect workflows\example.json
python -m cbn workflow validate workflows\example.json
python -m cbn workflow plan workflows\example.json
python -m cbn workflow run workflows\example.json --dry-run
```

工作流 runner 会处理：

- JSON 结构验证。
- task id 唯一性。
- 依赖图拓扑排序。
- 循环依赖检测。
- 上游结果选择器。
- dry-run 传播。
- blocked / failed / skipped / completed 等状态。

适合工作流化的任务：

- 先检查环境，再执行工具。
- 先生成文件，再让另一个工具消费文件。
- 先调用 CLI，再把 parser 输出交给后续节点。
- 把一组本地检查串成 acceptance flow。

## 协议与 Agent CLI Contract

CBN 保留了多个协议边界，但内部核心模型尽量保持协议无关。

### MCP / A2A / ACP

协议命令入口：

```powershell
python -m cbn protocol list
python -m cbn protocol matrix
python -m cbn protocol readiness
```

当前协议实现以 MVP 描述符、导出、检查、smoke suite 和适配边界为主。项目会明确标记 `wire_compatible` 状态，避免把描述符导出误认为完整协议服务器。

### Agent CLI Contract

Agent CLI Contract 位于：

```text
external_protocols/agent-cli-contract/
```

它定义了两个关键概念：

| 概念 | 说明 |
| --- | --- |
| `AgentCliCard` | 描述一个 agent CLI 能力卡片。CBN 可以将其映射为 ToolManifest。 |
| `RunReceipt` | 描述一次 agent CLI 运行结果。CBN 可以映射为 BridgeMessage、artifact、audit 和 event。 |

合约 smoke：

```powershell
python external_protocols\agent-cli-contract\scripts\conformance_smoke.py
```

Python validation 示例：

```powershell
$env:PYTHONPATH = "external_protocols\agent-cli-contract\python"
python -m agent_cli_contract validate card external_protocols\agent-cli-contract\fixtures\agent-cli-card.valid.json
python -m agent_cli_contract validate receipt external_protocols\agent-cli-contract\fixtures\run-receipt.valid.json
```

Node check：

```powershell
node external_protocols\agent-cli-contract\scripts\check.mjs
```

## 插件与外部适配

CBN 支持通过插件和 adapter 接入外部工具生态。

相关目录：

| 路径 | 作用 |
| --- | --- |
| `cbn_plugins/` | 插件操作运行器。 |
| `plugins/` | 插件元数据或内置插件相关内容。 |
| `external_plugins/` | 本地外部插件安装目录，通常不提交到 Git。 |
| `custom_adapters/` | 自定义 adapter 扩展点。 |
| `packages/adapter-cli-anything/` | CLI-Anything / CLI-Hub adapter package 边界。 |

插件命令：

```powershell
python -m cbn plugin list
python -m cbn plugin info cli-anything
python -m cbn plugin preflight cli-anything
```

具体插件是否可用取决于本机是否安装了对应外部工具、虚拟环境、Node package 或认证材料。

## 配置与运行时数据

### 本地配置

`.env` 用于本地环境变量，不应提交到 Git。不要在 README、manifest 或测试 fixture 中硬编码私有 token、绝对路径、账号、cookie 或机器相关配置。

### 运行时目录

`runtime/` 保存本地运行时状态，例如：

- audit logs。
- events。
- artifacts。
- approval store。
- 本地 manifest overlay。
- plugin runtime 状态。

这些内容通常是机器相关或运行生成的，不应作为源码提交。

### 外部插件目录

`external_plugins/` 适合放外部 tool hub、adapter、vendor runtime 或实验性插件。该目录通常只保留 `.gitkeep`，实际内容按本机安装。

### Manifest 与本地 overlay

建议将可复用能力放入 `manifests/`。机器相关能力、私有路径、实验命令或临时集成应放在 runtime overlay 或 ignored local config 中。

## 开发与测试

### Python 检查

```powershell
python -m cbn health
python -m unittest discover tests-unit
```

根目录 `package.json` 也提供了 Python 检查脚本：

```powershell
npm run check:python
npm run check:cbn
```

### 前端检查

```powershell
npm --workspace frontend run check
```

### Agent CLI Contract 检查

```powershell
python external_protocols\agent-cli-contract\scripts\conformance_smoke.py
node external_protocols\agent-cli-contract\scripts\check.mjs
```

### Rust 检查

```powershell
cargo check --workspace
```

### 推荐开发顺序

1. 先写或修改 manifest。
2. 跑 `python -m cbn registry validate`。
3. 跑 `python -m cbn call <capability-id> --dry-run`。
4. 添加 parser fixture。
5. 跑相关 `tests-unit`。
6. 如果涉及 workflow，跑 `workflow inspect`、`workflow validate` 和 `workflow run --dry-run`。
7. 如果涉及前端，跑 `npm --workspace frontend run check`。
8. 如果涉及协议边界，跑对应 `protocol` 或 `agent-cli-contract` smoke。

### 已验证的基础命令

以下命令在当前项目结构中属于基础验证入口：

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

## 常见问题

### 这是一个 CLI 工具还是一个前端应用？

两者都有。`python -m cbn` 是核心 CLI 和 runtime 入口；`frontend/` 是 Workflow Studio，用来可视化操作同一套能力网络。

### 为什么 registry 输出在不同机器上不同？

registry 会加载默认 manifest、本地 overlay、外部插件和可发现工具。某些能力依赖本机是否安装对应 CLI、插件或 runtime。

### dry-run 会写文件吗？

dry-run 不应执行真实外部副作用命令，但仍可能写入 CBN 自身的本地 runtime 记录，例如 artifact、event 或 audit，以便调试和追踪。

### `requirements.txt` 为什么是空的？

当前 Python runtime 有意 stdlib-first，依赖和包元数据主要在 `pyproject.toml` 中定义。`requirements.txt` 保留给后续 runtime dependency。

### 协议命令是否代表完整 MCP / A2A / ACP 实现？

不是。当前协议相关命令主要提供描述符导出、检查、矩阵、readiness 和 smoke 边界。是否 wire-compatible 以命令输出中的状态为准。

### 可以把 `.env`、`runtime/` 或 `external_plugins/` 提交吗？

通常不应该。这些目录或文件可能包含机器相关状态、私有路径、token、运行日志、产物或外部工具安装内容。

### 新增一个 CLI 能力应该从哪里开始？

优先从 `manifests/` 中的已有 manifest 参考起步，先写最小能力声明，再用 `registry validate` 和 `call --dry-run` 验证。只有当输出需要结构化消费时再添加 parser。

## 许可证

本项目基于 [MIT License](LICENSE) 发布。
