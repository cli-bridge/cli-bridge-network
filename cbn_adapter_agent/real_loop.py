"""Real Workflow Orchestration Agent loop — autonomous, long-horizon, function-calling.

This is the *built-in* bus agent (NOT a human operator). GLM drives the loop:
it receives a natural-language task, resolves it to registered CLI capabilities,
runs them FOR REAL through ``CapabilityExecutor`` (manifest -> policy -> approval
-> stdio dispatch -> parser -> BridgeMessage -> artifact/audit), observes the
results, and iterates until the task is done. Nothing here is simulated.

Auth needs (Obsidian API key, Jimeng OAuth) are surfaced as ``auth_ask`` events so
the host (daemon route / frontend chat) can collect them conversationally,
Codex-style. The agent never asks the user to paste secrets into its own reasoning
and never fabricates a result — if a capability is missing or errors, it reports
that honestly.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator

from cbn_adapter_agent.tool_use import store_session_secret


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
DEFAULT_MODEL = "GLM-5.1"
MANIFESTS_DIR = ROOT / "manifests"

# Secrets that may be supplied at runtime via the set_secret tool + .env overlay.
SECRET_ENV_NAMES = ("OBSIDIAN_API_KEY",)

# Extra usage hints keyed by the REAL registry capability_id (filename stem, not
# the manifest's metadata.id — those differ). Filled from registry.list() at runtime;
# this map only adds arg-format hints for the capabilities the agent is most likely
# to drive on the first real run.
CAPABILITY_HINTS = {
    "obsidian-cli.local-rest.note.read": "Read an Obsidian note. args=['<note-path>'] e.g. ['git.md']. Needs OBSIDIAN_API_KEY.",
    "jimeng.text2image.submit": "Jimeng/Dreamina text-to-image (async). args=['--prompt','<text>','--poll','30']. Needs login + credits.",
    "jimeng.query_result": "Poll a Jimeng task result. args=['--generate_id','<id>','--poll','20'].",
    "jimeng.list_task": "List recent Jimeng tasks. args=[].",
    "jimeng.user_credit": "Check Jimeng credit balance / login state. args=[].",
    "jimeng.version": "Jimeng CLI version (login probe). args=[].",
}


# --------------------------------------------------------------------------- #
# .env + GLM (OpenAI-compatible, supports tools/tool_calls; reasoning model)
# --------------------------------------------------------------------------- #
def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = ROOT / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
                value = value[1:-1]
            if name:
                values[name] = value
    values.update(os.environ)
    return values


def apply_secret_env(env: dict[str, str]) -> None:
    """Push known secrets into os.environ so subprocess CLIs (external_cli) inherit them."""
    for name in SECRET_ENV_NAMES:
        value = env.get(name)
        if value:
            os.environ[name] = value


def glm_chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]], env: dict[str, str], *, max_tokens: int = 4096) -> dict[str, Any]:
    base = (env.get("ZAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    payload: dict[str, Any] = {
        "model": env.get("ZAI_MODEL") or DEFAULT_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {env.get('ZAI_API_KEY', '')}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


# --------------------------------------------------------------------------- #
# Harness + tool schemas
# --------------------------------------------------------------------------- #
def harness_system(*, permission: str, capability_block: str) -> str:
    perm_guidance = {
        "full": "完全访问 (full): run every capability autonomously without asking; only stop for a human when a capability genuinely needs a credential/login you cannot supply via tools.",
        "auto": "自动审查 (auto): run read/local capabilities autonomously; for external-network or write capabilities, state what you are about to do then proceed unless it errors.",
        "default": "默认审批 (default): before each run_capability call, tell the user what you will run and wait — do not execute yet.",
    }[permission]
    return f"""你是 CBN 的 Workflow Orchestration Agent —— 内置总线 Agent（由 GLM 驱动）。
你的职责：把用户的自然语言任务，解析为已注册的 CLI capability，通过总线**真实执行**，观察结果，迭代直到完成。你不是一个模拟器：所有 run_capability 调用都会真实运行 CLI 并产生真实 artifact/audit。

能力命名 = `profile.action`。用 list_capabilities 查看已注册能力；用 run_capability(profile, action, args) 真实运行。
当前已注册能力（profile.action → 用法提示）：
{capability_block}

硬规则：
1. 绝不伪造结果。只能报告 run_capability 真正返回的内容。没跑过就别说跑了。
2. 如果任务需要的 CLI 不在已注册能力里，**停止并明确告诉用户缺什么**，不要臆造。
3. 如果一个能力返回认证错误（如 "API key required" / 未登录）：Obsidian 用 set_obsidian_key 设置；Jimeng 登录用 run_capability("jimeng","login",["--headless"]) 触发，把返回的登录链接/验证码通过 auth_ask 事件告诉用户，等用户授权后再继续。
4. 需要"整理/总结/改写"这类 LLM 变换（例如把笔记整理成文生图提示词）——你自己用推理完成，不要为此调用 CLI。
5. 真实工作流示例：读取 obsidian 笔记 → (你自己整理成提示词) → 提交即梦文生图 → 轮询取图 → 报告真实产物。
6. 每一步如实、简短地汇报真实结果（成功/失败/产物 id/错误）。

当前权限模式：{perm_guidance}
""".strip()


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_capabilities",
            "description": "List the CLI capabilities registered on the CBN bus (profile.action ids with usage hints).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_capability",
            "description": "Run a registered CLI capability FOR REAL through the CBN bus (manifest -> policy -> dispatch -> BridgeMessage -> audit). Returns the real stdout/result or an auth/policy error. Use the EXACT capability_id returned by list_capabilities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "capability_id": {"type": "string", "description": "exact capability id from list_capabilities, e.g. 'obsidian-cli.local-rest.note.read', 'jimeng.text2image.submit'"},
                    "args": {"type": "array", "items": {"type": "string"}, "description": "extra argv passed to the CLI, e.g. ['git.md'] or ['--prompt','a cat','--poll','30']"},
                },
                "required": ["capability_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_obsidian_key",
            "description": "Store the Obsidian Local REST API key for this session (Codex-style secret input). The key is kept only in the daemon process env overlay, never written to disk/git.",
            "parameters": {
                "type": "object",
                "properties": {"api_key": {"type": "string", "description": "Obsidian Local REST API key (raw, no 'Bearer' prefix)"}},
                "required": ["api_key"],
            },
        },
    },
]


# --------------------------------------------------------------------------- #
# Tool dispatch (real execution)
# --------------------------------------------------------------------------- #
def list_capabilities(registry: Any) -> list[dict[str, str]]:
    """Authoritative capability list straight from the registry (ids are filename
    stems, which differ from each manifest's metadata.id)."""
    items: list[dict[str, str]] = []
    caps: list[Any] = []
    if registry is not None and hasattr(registry, "list"):
        try:
            caps = list(registry.list())
        except Exception:
            caps = []
    for cap in caps:
        cid = getattr(cap, "capability_id", "") or ""
        if not cid:
            continue
        items.append(
            {
                "capability_id": cid,
                "title": getattr(cap, "title", "") or "",
                "hint": CAPABILITY_HINTS.get(cid, ""),
            }
        )
    return items


def _extract_output(result: dict[str, Any]) -> dict[str, Any]:
    """Pull a compact, agent-readable summary out of a CapabilityExecutor result.
    The executor returns top-level keys: ok/allowed/exit_code/reason/stdout/stderr/
    parsed/message(BridgeMessage)/artifacts."""
    summary: dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "allowed": result.get("allowed", True),
        "exit_code": result.get("exit_code"),
    }
    if not summary["allowed"]:
        summary["reason"] = result.get("reason") or "blocked by policy/approval"
    elif not summary["ok"]:
        # policy allowed the call but the CLI itself failed — say so explicitly so the
        # agent does not confuse this with a policy block and retry blindly.
        summary["reason"] = (
            f"capability executed but failed (exit_code={summary.get('exit_code')}); "
            "CLI produced no usable output — likely an external CLI error, not a CBN policy block"
        )
    stdout = result.get("stdout")
    if isinstance(stdout, str) and stdout:
        summary["stdout"] = stdout[:6000]
    stderr = result.get("stderr")
    if isinstance(stderr, str) and stderr.strip():
        summary["stderr"] = stderr[:1500]
    msg = result.get("message")
    if isinstance(msg, dict):
        summary["bridge_message"] = {
            "id": msg.get("id"),
            "capability_id": msg.get("capability_id"),
            "ok": msg.get("ok"),
        }
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list) and artifacts:
        summary["artifacts"] = [
            {"artifact_id": a.get("artifact_id"), "kind": a.get("kind"), "size_bytes": a.get("size_bytes")}
            for a in artifacts
            if isinstance(a, dict)
        ]
    # Clean parsed payload if the parser extracted structured content (e.g. note text).
    parsed = result.get("parsed")
    if isinstance(parsed, dict):
        data = parsed.get("data")
        if isinstance(data, dict):
            js = data.get("json")
            if isinstance(js, dict) and js.get("content"):
                summary["parsed_content"] = str(js["content"])[:4000]
    return summary


def dispatch_tool(
    name: str,
    args: dict[str, Any],
    *,
    executor: Any,
    registry: Any,
    env_store: dict[str, str],
    permission: str,
    audit_log: Any = None,
    event_bus: Any = None,
) -> dict[str, Any]:
    if name == "list_capabilities":
        return {"ok": True, "capabilities": list_capabilities(registry)}
    if name == "run_capability":
        capability_id = str(args.get("capability_id", "")).strip()
        if not capability_id:
            return {"ok": False, "error": "run_capability requires capability_id"}
        extra = tuple(str(a) for a in (args.get("args") or []))
        try:
            raw = executor.call(
                capability_id,
                extra_args=extra,
                dry_run=False,
                confirmed=(permission == "full"),
            )
        except Exception as exc:  # never let a tool crash kill the loop
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "capability_id": capability_id}
        return _extract_output(raw if isinstance(raw, dict) else {"ok": False, "raw": str(raw)})
    if name == "set_obsidian_key":
        value = str(args.get("api_key", "")).strip()
        result = store_session_secret(env_store, name="OBSIDIAN_API_KEY", value=value, audit_log=audit_log, event_bus=event_bus)
        if result.get("ok"):
            os.environ["OBSIDIAN_API_KEY"] = value
        return result
    return {"ok": False, "error": f"unknown tool: {name}"}


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #
EventCallback = Callable[[dict[str, Any]], None]


def run_agent_loop(
    *,
    message: str,
    permission: str,
    executor: Any,
    registry: Any,
    env_store: dict[str, str],
    on_event: EventCallback,
    audit_log: Any = None,
    event_bus: Any = None,
    max_iters: int = 12,
) -> None:
    env = load_env()
    apply_secret_env(env)
    # The executor builds each CLI subprocess env from executor.session_env (not
    # os.environ), so push .env secrets there too — otherwise obsidian/jimeng
    # subprocesses would not see OBSIDIAN_API_KEY on a fresh daemon.
    try:
        for secret_name in SECRET_ENV_NAMES:
            value = env.get(secret_name)
            if value:
                executor.session_env[secret_name] = value
    except Exception:
        pass
    if not env.get("ZAI_API_KEY"):
        on_event({"type": "error", "error": "ZAI_API_KEY is not configured (set it in .env)"})
        on_event({"type": "done", "ok": False})
        return

    caps = list_capabilities(registry)
    capability_block = "\n".join(
        f"- {item['capability_id']}" + (f" → {item['hint']}" if item.get("hint") else "") for item in caps
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": harness_system(permission=permission, capability_block=capability_block)},
        {"role": "user", "content": message},
    ]
    on_event({"type": "start", "permission": permission, "model": env.get("ZAI_MODEL") or DEFAULT_MODEL})

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
        finish = choice.get("finish_reason")
        reasoning = msg.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            on_event({"type": "thinking", "text": reasoning[:900]})

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            # echo the assistant turn (drop reasoning_content) then execute each call
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})
            for call in tool_calls:
                fn = call.get("function") or {}
                tool_name = fn.get("name", "")
                try:
                    parsed_args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    parsed_args = {}
                on_event({"type": "tool_call", "name": tool_name, "args": parsed_args})
                result = dispatch_tool(
                    tool_name,
                    parsed_args,
                    executor=executor,
                    registry=registry,
                    env_store=env_store,
                    permission=permission,
                    audit_log=audit_log,
                    event_bus=event_bus,
                )
                on_event({"type": "tool_result", "name": tool_name, "ok": bool(result.get("ok")), "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "name": tool_name,
                        "content": json.dumps(result, ensure_ascii=False)[:6000],
                    }
                )
            continue

        # no tool calls -> final answer
        content = msg.get("content") or ""
        on_event({"type": "final", "text": content, "finish_reason": finish, "iterations": iteration})
        on_event({"type": "done", "ok": True})
        return

    on_event({"type": "final", "text": "（已达最大迭代数或出错，Agent 停止。请查看上方各步真实结果。）", "iterations": max_iters})
    on_event({"type": "done", "ok": False})
