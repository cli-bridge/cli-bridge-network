"""Registration Agent loop — probe → install → generate Manifest IR → register a CLI.

Mirrors the WorkflowAgent real_loop (GLM function-calling → real execution → feedback
→ repeat) but its tools are the CLI-Anything hub pipeline. This is the interactive
"安装 CLI 并生成 Manifest IR" agent the owner couldn't find — it takes a natural-language
CLI request and drives the registration end-to-end: search the hub → install → generate
the manifest → write it to manifests/ → verify.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from cbn_adapter_agent.real_loop import load_env, glm_chat


ROOT = Path(__file__).resolve().parents[1]


REGISTER_SYSTEM = """你是 CBN 的注册 Agent（Registration Agent）。你的职责：把用户描述的 CLI 注册为 CBN 能力节点。

工作流程（按需调用工具）：
1. 用 search_market 搜索 CLI-Anything 市场里有没有对应的 harness。
2. 如果有 → install_harness 安装。
3. 安装后 → generate_manifest 生成 Manifest IR（能力卡片）。
4. → register_manifest 写入 manifests/ 目录（正式注册）。
5. → info_harness 或 list_registered 确认注册成功。

硬规则：
- 绝不伪造"已注册"。只有 register_manifest 真正写入后才能说注册成功。
- 如果市场里没有用户要的 CLI，明确告知 + 建议用 CLI-Anything 自己创建。
- 每步如实简短汇报。
- 绝不使用任何 emoji（图标/表情符号），只用纯文字 + 标点。
""".strip()


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_market",
            "description": "Search the CLI-Anything hub market for harnesses matching a query.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "search term, e.g. 'obsidian', 'image', 'git'"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "install_harness",
            "description": "Install a CLI harness from the CLI-Anything hub (pip from GitHub). May take 1-3 minutes.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "harness name, e.g. 'obsidian'"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_manifest",
            "description": "Generate the Manifest IR (capability card) for an installed harness.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "harness name"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "register_manifest",
            "description": "Write the generated manifest to manifests/ (officially register the CLI as a CBN node).",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "harness name"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_registered",
            "description": "List all currently registered CBN capabilities (capability ids).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _dispatch_register_tool(
    name: str,
    args: dict[str, Any],
    *,
    hub: Any,
    registry: Any,
) -> dict[str, Any]:
    if name == "search_market":
        query = str(args.get("query", ""))
        result = hub.search_market(query) if query else hub.list_market()
        stdout = getattr(result, "stdout", "") or ""
        try:
            items = json.loads(stdout) if stdout else []
        except (ValueError, TypeError):
            items = []
        # compact: just names + descriptions
        compact = [{"name": i.get("name"), "description": str(i.get("description", ""))[:100]} for i in items[:15]]
        return {"ok": True, "matches": compact, "count": len(items)}
    if name == "install_harness":
        harness = str(args.get("name", ""))
        if not harness:
            return {"ok": False, "error": "name is required"}
        entrypoint = hub.status().get("entrypoint_path") or "cli-hub"
        try:
            proc = subprocess.run(
                [entrypoint, "install", harness],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
            )
            return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout": (proc.stdout or "")[:800], "stderr": (proc.stderr or "")[:400]}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if name == "generate_manifest":
        harness = str(args.get("name", ""))
        if not harness:
            return {"ok": False, "error": "name is required"}
        try:
            manifest = hub.manifest_for_harness(harness)
            return {"ok": bool(manifest), "manifest": manifest}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if name == "register_manifest":
        harness = str(args.get("name", ""))
        if not harness:
            return {"ok": False, "error": "name is required"}
        try:
            result = hub.write_harness_manifest(harness)
            return {"ok": bool(result), "result": result}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if name == "list_registered":
        return {"ok": True, "capabilities": [c.capability_id for c in registry.list()]}
    return {"ok": False, "error": f"unknown tool: {name}"}


EventCallback = Callable[[dict[str, Any]], None]


def run_register_loop(
    *,
    message: str,
    hub: Any,
    registry: Any,
    on_event: EventCallback,
    max_iters: int = 12,
) -> None:
    env = load_env()
    # also push secrets to os.environ
    for k in ("OBSIDIAN_API_KEY",):
        v = env.get(k)
        if v:
            os.environ[k] = v
    if not env.get("ZAI_API_KEY"):
        on_event({"type": "error", "error": "ZAI_API_KEY is not configured"})
        on_event({"type": "done", "ok": False})
        return

    registered_list = [c.capability_id for c in registry.list()]
    system = REGISTER_SYSTEM + f"\n\n当前已注册 {len(registered_list)} 个能力。"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": message},
    ]
    on_event({"type": "start", "registered_count": len(registered_list), "model": env.get("ZAI_MODEL", "GLM-5.1")})

    for iteration in range(1, max_iters + 1):
        try:
            response = glm_chat(messages, TOOLS, env)
        except urllib.error.HTTPError as exc:
            on_event({"type": "error", "error": f"GLM HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}"})
            break
        except Exception as exc:
            on_event({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
            break

        choice = (response.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        reasoning = msg.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            on_event({"type": "thinking", "text": reasoning[:900]})

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})
            for call in tool_calls:
                fn = call.get("function") or {}
                tool_name = fn.get("name", "")
                try:
                    parsed_args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    parsed_args = {}
                on_event({"type": "tool_call", "name": tool_name, "args": parsed_args})
                result = _dispatch_register_tool(tool_name, parsed_args, hub=hub, registry=registry)
                on_event({"type": "tool_result", "name": tool_name, "ok": bool(result.get("ok")), "result": result})
                messages.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""), "name": tool_name, "content": json.dumps(result, ensure_ascii=False)[:6000]}
                )
            continue

        content = msg.get("content") or ""
        on_event({"type": "final", "text": content, "iterations": iteration})
        on_event({"type": "done", "ok": True})
        return

    on_event({"type": "final", "text": "（已达最大迭代数，注册 Agent 停止。）", "iterations": max_iters})
    on_event({"type": "done", "ok": False})
