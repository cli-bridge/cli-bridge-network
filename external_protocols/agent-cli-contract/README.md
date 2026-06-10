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
