# Agent CLI Contract

Agent CLI Contract is the small external protocol boundary for CBN-compatible
CLI and Agent adapters. It is intentionally independent from CLI Bridge Network
runtime modules.

It defines:

- `AgentCliCard`: how a CLI or agent declares callable commands.
- `RunReceipt`: how a completed run reports status, raw output, parsed payload,
  artifacts, and correlation metadata.

This package must not import or depend on CBN daemon, workflow, artifact store,
audit, MCP, A2A, or ACP modules. CBN consumes this protocol by mapping
`AgentCliCard` to `ToolManifest` and `RunReceipt` to `BridgeMessage`,
artifact records, audit entries, and events.

## Smoke

```powershell
python external_protocols/agent-cli-contract/scripts/conformance_smoke.py
```

## Python Package

The Python package is standalone and has no runtime dependency on CBN modules.
It can be installed from this directory and used as a small validator CLI:

```powershell
python -m pip install external_protocols/agent-cli-contract
agent-cli-contract validate card external_protocols/agent-cli-contract/fixtures/agent-cli-card.valid.json
agent-cli-contract validate receipt external_protocols/agent-cli-contract/fixtures/run-receipt.valid.json
```

For local source-tree checks without installation:

```powershell
$env:PYTHONPATH = "external_protocols/agent-cli-contract/python"
python -m agent_cli_contract validate card external_protocols/agent-cli-contract/fixtures/agent-cli-card.valid.json
python -m agent_cli_contract validate receipt external_protocols/agent-cli-contract/fixtures/run-receipt.valid.json
```
