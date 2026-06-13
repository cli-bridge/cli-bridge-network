# Legacy Ribbon Workbench Snapshot

This directory preserves the previous Electron Ribbon Workbench design before
the AFFiNE-style command-canvas redesign.

These files are intentionally not imported by `frontend/src/main.ts`.
They are kept as a recoverable design snapshot while the active app entry
continues to use `frontend/src/App.vue` and `frontend/src/styles.css`.

Snapshot contents:

- `App.RibbonWorkbench.vue`: previous full Vue workbench implementation.
- `styles.ribbon-workbench.css`: previous workbench stylesheet.

Do not delete this directory while the AFFiNE-style redesign is being evaluated.
