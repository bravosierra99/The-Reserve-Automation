# End-to-End Browser Tests

Real E2E tests that run a browser and test the complete user experience.

## Setup (One Time)

Install browser dependencies in WSL:

```bash
sudo apt-get update
sudo apt-get install -y libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libnss3 libgtk-3-0
```

Browsers are already installed via Playwright.

## Running Tests

Run all browser tests:
```bash
uv run pytest tests/e2e/test_browser_upload_flow.py -v
```

Run specific test:
```bash
uv run pytest tests/e2e/test_browser_upload_flow.py::TestBrowserUploadFlow::test_upload_bottle_opens_modal -v
```

## What These Tests Do

**Unlike API-only tests**, these tests:
- Start a real web server
- Launch Firefox browser
- Load actual HTML pages
- Execute JavaScript
- Interact with UI elements (click buttons, fill forms)
- Verify modal opens/closes
- Check for success messages
- Take screenshots on failure

**These would have caught:**
- Missing JavaScript includes
- Modal not opening after upload
- Save button not showing feedback
- Frontend/backend integration issues

## Test Coverage

- `test_upload_page_loads` - Basic page rendering
- `test_upload_bottle_opens_modal` - **CRITICAL** - Full upload → extract → modal flow
- `test_modal_save_shows_feedback` - Save button shows success toast
- `test_management_page_loads` - Management grid loads
- `test_click_bottle_opens_modal` - Click bottle opens modal
- `test_modal_save_reloads_page` - Save in management mode works

## Debugging Failed Tests

Screenshots are saved to `/tmp/` on failure.
Console logs are printed to help debug JavaScript errors.
