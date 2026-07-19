---
name: verify
description: Launch and drive The Reserve web app locally to verify a change at the UI surface (browser), including auth setup and Playwright gotchas in WSL.
---

# Verifying changes in the running web app

## Launch

```bash
AUTH_DEV_ENABLED=true ./start-web.sh    # background it; serves http://localhost:8000
```

- Without `AUTH_DEV_ENABLED=true` every API call is 401 (committed
  `config/auth.yaml` has dev mode off; the env var overrides it).
- Port already in use? An orphaned reload child survives `pkill -f uvicorn` —
  find it with `ss -tlnp | grep :8000` and kill that PID directly.
- Dev DB is `data/reserve.db` (seed data mirroring much of prod, incl. the
  George T. Stagg 2018/2024/2025 near-duplicates — good disambiguation cases).
  Safe to write; clean up test artifacts afterwards.

## Drive (browser)

The Playwright **MCP server does not work here** (pinned to the `chrome`
channel, not installed, no sudo). Use the repo's Python Playwright instead —
chromium is installed and headless works in WSL:

```bash
uv run python - <<'EOF'
from playwright.sync_api import sync_playwright
p = sync_playwright().start(); b = p.chromium.launch()
page = b.new_context(viewport={"width":1280,"height":900}).new_page()
page.on("dialog", lambda d: d.accept())   # app uses alert() on saves
page.goto("http://localhost:8000/bottles")
page.wait_for_timeout(2000)               # Alpine init + fetches
page.screenshot(path="shot.png")
b.close(); p.stop()
EOF
```

## Flows worth driving

- **Bottles grid**: `/bottles`; card click opens the editor modal;
  `/bottles?bottle=<id>` deep-links straight into a bottle's modal.
- **Tasting wizard**: `+ Tasting` on a card → `/manual-tasting`
  (`input[x-model='tasterName']`, Next → Next → Save; save fires an alert
  then redirects to `/bottles?bottle=<id>`).
- **Create event picker**: `/management` → button "🎭 Manage Events" →
  visible "Create Event" button (beware: a hidden submit span also matches
  that text) → `input[x-model='eventBottleSearchQuery']`.

## Gotchas

- Alpine pages need ~1-2s `wait_for_timeout` after goto before asserting.
- Text like "Manage Events" appears twice (card + heading) — use
  `get_by_role("button", ...)` or `>> visible=true`.
