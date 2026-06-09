# @cli-bridge/dashboard

Draft CBN Console package. The first version is intentionally static and
button-heavy: it exposes the management surface while calling the MVP daemon
API for routes that already exist.

Start the daemon first:

```powershell
python -m cbn daemon serve --host 127.0.0.1 --port 8787
```

Serve the dashboard from a local origin:

```powershell
npm --workspace @cli-bridge/dashboard run serve
```

Then open `http://127.0.0.1:5173`.

Run the lightweight static check:

```powershell
npm --workspace @cli-bridge/dashboard run check
```

The page currently queues command previews such as:

```powershell
python -m cbn plugin plan cli-anything
python -m cbn plugin check-update cli-anything
python -m cbn plugin check-update cli-anything --remote
python -m cbn plugin gate cli-anything --action update
python -m cbn plugin plan cli-anything --action update
python -m cbn plugin install cli-anything --yes
python -m cbn plugin update cli-anything --yes
```

Buttons with daemon API support call `http://127.0.0.1:8787` and still stage
the equivalent command as a fallback. Update checks are read-only by default;
the remote update check queries upstream state but still does not execute
`git pull` or pip changes. Confirmed install, update, manifest write, and
harness lifecycle buttons ask for browser confirmation before sending
`confirmed=true`. Serving from `127.0.0.1` keeps the dashboard inside the
daemon's local Origin allowlist.

`Rank Candidates` and `Rank + Probe` call the compact CLI-Anything candidates
API and render `candidate_summary` into the sidecar. Candidate actions use
read-only evaluate/prepare calls or an unconfirmed install plan, so scanning a
market list does not install a harness.
