# CLI Bridge Network

CLI Bridge Network (CBN) is a local-first runtime for registering, inspecting,
calling, and coordinating CLI and agent-facing capabilities.

This public repository is kept to the runnable project core: Python packages,
protocol adapters, plugin/runtime code, manifests, workflow examples, package
skeletons, and tests. Local research notes, generated reports, architecture
drafts, and imported reference material are intentionally ignored.

## Quick Check

```powershell
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -m cbn --version
python -m cbn registry list
python -m cbn plugin list
```

## Useful Commands

```powershell
python -m cbn call git.version --dry-run
python -m cbn event tail
python -m cbn artifact list
python -m cbn parser list
python -m cbn protocol export all
python -m cbn approvals list --status pending
python -m cbn workflow run workflows/example.json --dry-run
python -m cbn daemon routes
```
