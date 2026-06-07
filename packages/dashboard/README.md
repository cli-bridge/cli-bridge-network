# @cli-bridge/dashboard

Draft CBN Console package. The first version is intentionally static and
button-heavy: it exposes the management surface before the backend API is
finalized.

Open directly:

```powershell
start packages\dashboard\src\index.html
```

Run the lightweight static check:

```powershell
npm --workspace @cli-bridge/dashboard run check
```

The page currently queues command previews such as:

```powershell
python -m cbn plugin plan cli-anything
python -m cbn plugin install cli-anything --yes
python -m cbn plugin update cli-anything --yes
```

Future work should replace command preview handlers with CBN gateway API calls.
