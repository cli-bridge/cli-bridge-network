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
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator

from cbn_adapter_agent.tool_use import store_session_secret
from cbn_threads.workflow_capture import WorkflowCapture


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
# Streaming GLM (SSE) — same endpoint/auth/payload as glm_chat, with stream=True
# --------------------------------------------------------------------------- #
def _parse_sse_line(line: str) -> dict[str, Any] | None:
    """Parse one raw line of an SSE stream.

    Returns:
        - ``None`` for non-data lines (comments, ``event:``, ``id:``, ``retry:``, blanks).
        - ``{"_done": True}`` sentinel for the terminal ``data: [DONE]`` marker.
        - the parsed JSON dict for any ``data: {json}`` payload (OpenAI-compatible
          chat.completion.chunk shape: ``choices[0].delta`` etc.).

    The payload object itself is returned as-is so callers can pull
    ``choices[0].delta.content / .reasoning_content / .tool_calls`` and
    ``choices[0].finish_reason`` directly.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        # blank line or SSE comment (begins with ':')
        return None
    if not stripped.startswith("data:"):
        # other SSE field prefixes (event:, id:, retry:) — not payload data
        return None
    payload = stripped[len("data:"):].lstrip()
    if payload == "[DONE]":
        return {"_done": True}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        # Malformed JSON fragment — ignore rather than crash the stream.
        return None
    return parsed


def glm_chat_stream(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    env: dict[str, str],
    *,
    max_tokens: int = 4098,
) -> Iterator[dict[str, Any]]:
    """Stream an OpenAI-compatible chat completion from GLM (z.ai).

    POSTs to the SAME endpoint/auth/payload shape as :func:`glm_chat`, but with
    ``stream: True``, then reads the urllib response line-by-line in text mode
    (utf-8) and yields each parsed SSE payload (the JSON dict returned by
    :func:`_parse_sse_line`). The terminal ``[DONE]`` sentinel is yielded too, so
    callers can detect end-of-stream; non-data lines are silently skipped.

    Each yielded dict is an OpenAI-compatible ``chat.completion.chunk``:
    ``choices[0].delta`` may carry ``.content`` (str), ``.reasoning_content``
    (str), and/or ``.tool_calls`` (a list of partial fragments
    ``{index, id?, function?:{name?, arguments?}}`` — fragments for the same
    ``index`` arrive incrementally across chunks; ``function.arguments`` is a
    JSON string that grows chunk by chunk). The final chunk also surfaces
    ``choices[0].finish_reason``.

    ``urllib.error.HTTPError`` is re-raised (like :func:`glm_chat`) so the agent
    loop's existing error branch handles it.
    """
    base = (env.get("ZAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    payload: dict[str, Any] = {
        "model": env.get("ZAI_MODEL") or DEFAULT_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": True,
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
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    # HTTPError propagates to the caller (re-raised, same contract as glm_chat).
    response = urllib.request.urlopen(request, timeout=180)
    try:
        # Read line-by-line in text mode. The server emits SSE: lines terminated
        # by \n; decode lazily so streaming actually reaches the caller chunk by
        # chunk instead of buffering the whole body.
        for raw in response:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            parsed = _parse_sse_line(raw)
            if parsed is not None:
                yield parsed
    finally:
        response.close()


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
3. 如果一个能力返回认证错误（如 "API key required" / 未登录）：Obsidian 用 set_obsidian_key 设置；其它 key/login 类阻塞系统会抛出 cooperation_required，你按提示让用户配合即可。
4. 需要"整理/总结/改写"这类 LLM 变换（例如把笔记整理成文生图提示词）——你自己用推理完成，不要为此调用 CLI。
5. 真实工作流示例：读取 obsidian 笔记 → (你自己整理成提示词) → 提交即梦文生图 → 轮询取图 → 报告真实产物。
6. 每一步如实、简短地汇报真实结果（成功/失败/产物 id/错误）。
7. **像一个正常助手一样对话**：用户如果只是闲聊、问普通问题、或任务根本不需要调 CLI，就直接正常回答，**不要硬编排工作流**。
8. **遇到需要用户配合的阻塞**（缺 key / 钱包未配对 / 未登录 / CLI 未装 / 权限额度不足），系统会发 cooperation_required——你**立刻停下来**，用大白话告诉用户具体要做什么；等用户回复"好了/done"后，**先重新调用对应能力（或其 status/help 探针）验证通过**，再继续原任务，绝不跳过验证。
9. 调用一个你不确定是否就绪的能力前，可以先调它的 status/help/version 探针确认环境，避免无谓失败——尤其是涉及钱包/登录/外部账号的能力。
10. **绝不使用任何 emoji（图标/表情符号）**。所有回复、总结、卡片内容只用纯文字 + 标点——避免终端编码问题，保持输出干净。

工作流编排方式：当任务确实需要编排多个能力时，先用一两句大白话说出你的计划（例如"我先读取笔记，再整理成提示词，然后提交即梦文生图"），然后一步一步真实执行，每一步如实汇报结果；在非 full 权限下，每次 run_capability 之前先简短说明你要跑什么再跑。纯聊天或普通问答不要套这个流程——直接正常回答即可。

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


# --------------------------------------------------------------------------- #
# Cooperation gate — surface missing-setup blockers (auth/pairing/login/install)
# Mirrors auth_ask but generalized: any capability that fails because of a missing
# human-setup step becomes a structured "needs cooperation" request the host can
# render (amber card) and the user resolves, then the agent re-verifies on resume.
# --------------------------------------------------------------------------- #
_BLOCKER_PATTERNS: list[tuple[str, str, str]] = [
    (r"api key required|obsidian_api_key|missing.{0,6}key|unauthorized", "auth",
     "需要 API key —— 用下面的输入框粘贴 key，或在 .env 里设好后回复我，我会重新验证。"),
    (r"not.{0,6}paired|pairing|healthy.{0,4}false|unsupported protocol scheme|wallet.{0,12}not.{0,12}configured", "pairing",
     "CAW 钱包未配对 —— 请跑 `caw onboard` 配对 Cobo 账号（或提供 API key + AGENT_WALLET_API_URL），完成后回复我。"),
    (r"not logged in|login required|not.{0,6}authenticated|not authorized|需要登录", "login",
     "需要登录 —— 请完成对应 CLI 的登录授权，完成后回复我，我会重新验证。"),
    (r"command not found|no such file|not recognized|cli-hub.{0,12}not|未安装|not installed", "install",
     "CLI 未安装 —— 请先安装对应工具（注册 Agent / cli-hub install），完成后回复我。"),
    (r"requires?.{0,12}(vip|maestro)|(vip|maestro).{0,12}(required|needed|only|plan)|permission denied|no.{0,6}permission|额度|insufficient", "entitlement",
     "账号权限/额度不足（如即梦需 Maestro VIP）—— 请升级/充值后回复我，我会重新验证。"),
]

_BLOCKER_FINAL = {
    "auth": "缺凭证", "pairing": "钱包未配对", "login": "未登录",
    "install": "CLI 未安装", "entitlement": "权限/额度不足",
}


def _detect_cooperation(result: dict[str, Any], capability_id: str) -> dict[str, Any] | None:
    """If a failed tool result smells like a missing-setup blocker, return a
    cooperation_required payload; else None (caller keeps looping / lets GLM handle)."""
    haystack = " ".join([
        str(result.get("reason") or ""),
        str(result.get("stdout") or ""),
        str(result.get("stderr") or ""),
    ]).lower()
    for pattern, kind, message in _BLOCKER_PATTERNS:
        if re.search(pattern, haystack):
            return {
                "type": "cooperation_required",
                "capability_id": capability_id,
                "blocker_kind": kind,
                "message": message,
                "probe": {"capability_id": capability_id,
                          "note": "用户配合后，重新调用此能力（或其 status/help 探针）验证通过再继续"},
                "raw": (result.get("stdout") or result.get("stderr") or result.get("reason") or "")[:300],
            }
    return None


def _cooperation_final_text(coop: dict[str, Any]) -> str:
    kind = coop.get("blocker_kind", "unknown")
    label = _BLOCKER_FINAL.get(kind, kind)
    return (f"[!] 需要你配合 —— {label}。\n{coop.get('message', '')}\n"
            f"（这是「{label}」类阻塞，我不会伪造结果。你处理好后回复我，我会先重新验证再继续原任务。）")


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
    capture: WorkflowCapture | None = None,
) -> dict[str, Any]:
    if name == "list_capabilities":
        return {"ok": True, "capabilities": list_capabilities(registry)}
    if name == "run_capability":
        capability_id = str(args.get("capability_id", "")).strip()
        if not capability_id:
            return {"ok": False, "error": "run_capability requires capability_id"}
        extra = tuple(str(a) for a in (args.get("args") or []))
        # Record every real capability execution at the execution choke point so
        # the captured workflow never depends on the streamed-event shape (a
        # previous streaming refactor risked losing the capture hook that lived
        # only in the route's on_event filter).
        if capture is not None:
            capture.record_capability_call(capability_id, extra)
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
    capture: WorkflowCapture | None = None,
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
            # Streaming consumption of GLM (SSE). We accumulate content/reasoning
            # incrementally (emitting text/thinking deltas live) and reassemble
            # tool_call fragments by index across chunks, exactly as the
            # OpenAI-compatible streaming spec dictates.
            assistant_content_parts: list[str] = []
            reasoning_parts: list[str] = []
            # tool_call fragments keyed by index; first fragment for an index sets
            # id + function.name, subsequent fragments append to function.arguments.
            assembled: dict[int, dict[str, Any]] = {}
            finish: str | None = None

            for chunk in glm_chat_stream(messages, TOOLS, env):
                if chunk.get("_done"):
                    # terminal [DONE] sentinel — end of stream
                    break
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                delta = choice.get("delta") or {}

                content_delta = delta.get("content")
                if isinstance(content_delta, str) and content_delta:
                    assistant_content_parts.append(content_delta)
                    on_event({"type": "text", "delta": content_delta})

                reasoning_delta = delta.get("reasoning_content")
                if isinstance(reasoning_delta, str) and reasoning_delta:
                    reasoning_parts.append(reasoning_delta)
                    on_event({"type": "thinking", "text": "".join(reasoning_parts)[:900]})

                tc_frags = delta.get("tool_calls")
                if isinstance(tc_frags, list):
                    for frag in tc_frags:
                        if not isinstance(frag, dict):
                            continue
                        idx = frag.get("index", 0)
                        slot = assembled.get(idx)
                        if slot is None:
                            slot = {
                                "id": frag.get("id", ""),
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                            assembled[idx] = slot
                        if frag.get("id") and not slot["id"]:
                            slot["id"] = frag["id"]
                        fn = frag.get("function") or {}
                        if fn.get("name") and not slot["function"]["name"]:
                            slot["function"]["name"] = fn["name"]
                        arg_chunk = fn.get("arguments")
                        if isinstance(arg_chunk, str):
                            slot["function"]["arguments"] += arg_chunk
        except urllib.error.HTTPError as exc:
            on_event({"type": "error", "error": f"GLM HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}"})
            break
        except Exception as exc:
            on_event({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
            break

        assistant_content = "".join(assistant_content_parts)
        tool_calls = [assembled[k] for k in sorted(assembled.keys())]
        if tool_calls and not tool_calls[0]["function"]["name"]:
            # a stream that declared tool_calls but never named them is not a
            # real tool turn — treat as chat so we don't dispatch anonymously.
            tool_calls = []

        if tool_calls:
            # Intent = workflow: echo the assistant turn (drop reasoning) then
            # execute each call exactly as the pre-streaming path did.
            on_event({"type": "intent", "intent": "workflow"})
            messages.append(
                {"role": "assistant", "content": assistant_content, "tool_calls": tool_calls}
            )
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
                    capture=capture,
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
                # cooperation gate: a capability FAILED, OR returned ok=True but reported
                # an UNHEALTHY/blocked state (status/health probes like caw.status return
                # ok=True with content {"healthy": false}). Detect either way and PAUSE so
                # the user can cooperate; on resume GLM re-probes per harness rule 8.
                coop = _detect_cooperation(result, str(parsed_args.get("capability_id", "")))
                if coop:
                    on_event(coop)
                    on_event({"type": "final", "text": _cooperation_final_text(coop),
                              "finish_reason": "cooperation_required", "iterations": iteration})
                    on_event({"type": "done", "ok": False, "waiting_for_cooperation": True,
                              "blocker_kind": coop["blocker_kind"]})
                    return
            continue

        # no tool calls -> Intent = chat: pure streamed answer, no bus work.
        on_event({"type": "intent", "intent": "chat"})
        on_event({"type": "final", "text": assistant_content, "finish_reason": finish, "iterations": iteration})
        on_event({"type": "done", "ok": True})
        return

    on_event({"type": "final", "text": "（已达最大迭代数或出错，Agent 停止。请查看上方各步真实结果。）", "iterations": max_iters})
    on_event({"type": "done", "ok": False})
