"""
E2E tests for duplicate detection workflow.

These tests verify that:
1. Duplicate detection triggers when saving a bottle that matches an existing one
2. The duplicate dialog appears with correct options
3. Each resolution option (Skip, Save as New, Replace) works correctly
"""




class TestDuplicateDetection:
    """Test duplicate detection and resolution workflows."""

    def test_duplicate_skip(self, web_server, sample_image, browser_no_cache, test_vault):
        """
        Test: Skip button dismisses dialog without saving.

        Flow:
        1. Upload bottle that matches ORIGINAL_PRODUCER
        2. Click Save → duplicate detected
        3. Click Skip
        4. Verify: No new bottle created, ORIGINAL_PRODUCER still exists
        """
        page = browser_no_cache.new_page()

        # Capture console logs for debugging
        console_logs = []
        page.on("console", lambda msg: console_logs.append(f"{msg.type}: {msg.text}"))

        # Capture network requests to see API calls
        network_logs = []
        save_responses = []

        def log_request(request):
            network_logs.append(f"REQUEST: {request.method} {request.url}")
            # Log save request body for debugging
            if '/api/v1/bottles/save' in request.url and request.method == 'POST':
                try:
                    import json
                    post_data = request.post_data
                    if post_data:
                        data = json.loads(post_data)
                        bottle_data = data.get('bottle', {})
                        save_responses.append(f"Save request bottle: producer={bottle_data.get('producer')}, name={bottle_data.get('name')}, type={bottle_data.get('type')}, force_save={data.get('force_save')}")
                except:
                    pass

        def log_response(response):
            network_logs.append(f"RESPONSE: {response.status} {response.url}")
            # Capture save endpoint responses for detailed debugging
            if '/api/v1/bottles/save' in response.url:
                try:
                    body = response.json()
                    save_responses.append(f"Save response: {body}")
                except:
                    save_responses.append(f"Save response (text): {response.text()}")

        page.on("request", log_request)
        page.on("response", log_response)

        vault_path = test_vault
        whiskey_dir = vault_path / "1_Whiskeys"

        # Verify fixture bottle exists
        fixture_bottle = whiskey_dir / "Weller - THE ORIGINAL WHEATED BOURBON"
        assert fixture_bottle.exists(), f"Fixture bottle not found: {fixture_bottle}"

        # Upload bourbon_001.jpg → extracts as "Weller" → matches existing Weller bottle
        page.goto(f"{web_server}/upload")
        page.click("button:has-text('Single Bottle')")
        page.wait_for_selector("text=How many bottles?", timeout=5000)
        page.set_input_files("input[type='file']", sample_image)
        page.click("text=✓ Upload & Extract")

        # Wait for modal to open
        page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=60000)

        # Click Save → should trigger duplicate detection
        save_button = page.locator("button:has-text('💾 Save')")
        save_button.click(force=True)

        # Wait for duplicate detection to complete by checking showDuplicateDialog property
        # Add debug logging with JSON.stringify so we can see actual values
        page.evaluate("""() => {
            const uploadForm = document.querySelector('[x-data="uploadForm()"]');
            if (uploadForm && uploadForm._x_dataStack) {
                const editor = uploadForm._x_dataStack[0].bottleEditor;
                const state = {
                    isOpen: editor.isOpen,
                    saving: editor.saving,
                    showDuplicateDialog: editor.showDuplicateDialog,
                    hasDuplicates: !!editor.duplicates,
                    duplicatesCount: editor.duplicates?.length
                };
                console.log('🔍 Editor state:', JSON.stringify(state));

                // Log updates every 500ms
                const checkState = () => {
                    const currentState = {
                        saving: editor.saving,
                        showDuplicateDialog: editor.showDuplicateDialog,
                        duplicatesCount: editor.duplicates?.length
                    };
                    console.log('🔍 State check:', JSON.stringify(currentState));
                };
                setInterval(checkState, 500);
            }
        }""")

        try:
            page.wait_for_function("""() => {
                const uploadForm = document.querySelector('[x-data="uploadForm()"]');
                if (!uploadForm || !uploadForm._x_dataStack) return false;
                const editor = uploadForm._x_dataStack[0].bottleEditor;
                return editor && editor.showDuplicateDialog === true;
            }""", timeout=15000)
        except Exception:
            # Print console and network logs for debugging
            print("\n=== Console logs ===")
            for log in console_logs[-30:]:
                print(log)
            print("\n=== Network logs ===")
            for log in network_logs:
                if '/api/' in log:
                    print(log)
            print("\n=== Save responses ===")
            for resp in save_responses:
                print(resp)
            raise

        # Call Skip action via Alpine component
        page.evaluate("""() => {
            const uploadForm = document.querySelector('[x-data="uploadForm()"]');
            uploadForm._x_dataStack[0].bottleEditor.handleDuplicateResolution('skip');
        }""")

        # Wait for dialog to close
        page.wait_for_timeout(1000)

        # Verify: Only original Weller bottle exists, no new bottle created
        # Use specific pattern to match only the simple Weller bottle (not Buffalo Trace Weller)
        weller_bottles = list(whiskey_dir.glob("Weller - THE ORIGINAL*"))

        assert len(weller_bottles) == 1, f"Expected 1 Weller bottle (skip should not create duplicate), found {len(weller_bottles)}: {[b.name for b in weller_bottles]}"

    def test_duplicate_save_as_new(self, web_server, sample_image, browser_no_cache, test_vault):
        """
        Test: Save as New creates a second bottle.

        Flow:
        1. Upload bottle that matches existing Weller bottle
        2. Click Save → duplicate detected
        3. Click Save as New Bottle
        4. Verify: Both original and new Weller bottles exist
        """
        page = browser_no_cache.new_page()

        vault_path = test_vault
        whiskey_dir = vault_path / "1_Whiskeys"

        # Verify fixture bottle exists
        fixture_bottle = whiskey_dir / "Weller - THE ORIGINAL WHEATED BOURBON"
        assert fixture_bottle.exists(), f"Fixture bottle not found: {fixture_bottle}"

        # Upload bourbon_001.jpg
        page.goto(f"{web_server}/upload")
        page.click("button:has-text('Single Bottle')")
        page.wait_for_selector("text=How many bottles?", timeout=5000)
        page.set_input_files("input[type='file']", sample_image)
        page.click("text=✓ Upload & Extract")

        # Wait for modal
        page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=60000)

        # Click Save
        save_button = page.locator("button:has-text('💾 Save')")
        save_button.click(force=True)

        # Wait for duplicate detection
        page.wait_for_function("""() => {
            const uploadForm = document.querySelector('[x-data="uploadForm()"]');
            if (!uploadForm || !uploadForm._x_dataStack) return false;
            const editor = uploadForm._x_dataStack[0].bottleEditor;
            return editor && editor.showDuplicateDialog === true;
        }""", timeout=10000)

        # Call Save as New action via Alpine component
        page.evaluate("""() => {
            const uploadForm = document.querySelector('[x-data="uploadForm()"]');
            uploadForm._x_dataStack[0].bottleEditor.handleDuplicateResolution('new');
        }""")

        # Wait for save to complete
        page.wait_for_timeout(3000)

        # Verify: Two Weller bottles exist now (original + new)
        # Use specific pattern to match only the simple Weller bottles (not Buffalo Trace Weller)
        weller_bottles = list(whiskey_dir.glob("Weller - THE ORIGINAL*"))

        assert len(weller_bottles) == 2, f"Expected 2 Weller bottles (original + new), found {len(weller_bottles)}: {[b.name for b in weller_bottles]}"

        # Verify both have different names (one should have a unique suffix)
        bottle_names = [b.name for b in weller_bottles]
        assert len(set(bottle_names)) == 2, f"Expected 2 unique bottle names, found: {bottle_names}"

    def test_duplicate_replace_existing(self, web_server, sample_image, browser_no_cache, test_vault):
        """
        Test: Replace This Bottle deletes old, creates new.

        Flow:
        1. Upload bottle that matches existing Weller bottle
        2. Click Save → duplicate detected
        3. Click Replace This Bottle (for first duplicate)
        4. Verify: Still only 1 Weller bottle (replaced, not duplicated)

        Note: This test modifies the fixture bottle. The test_vault fixture
        recreates it for the next test, so this is safe.
        """
        page = browser_no_cache.new_page()

        vault_path = test_vault
        whiskey_dir = vault_path / "1_Whiskeys"

        # Verify fixture bottle exists
        fixture_bottle = whiskey_dir / "Weller - THE ORIGINAL WHEATED BOURBON"
        assert fixture_bottle.exists(), f"Fixture bottle not found: {fixture_bottle}"

        # Upload bourbon_001.jpg
        page.goto(f"{web_server}/upload")
        page.click("button:has-text('Single Bottle')")
        page.wait_for_selector("text=How many bottles?", timeout=5000)
        page.set_input_files("input[type='file']", sample_image)
        page.click("text=✓ Upload & Extract")

        # Wait for modal
        page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=60000)

        # Click Save
        save_button = page.locator("button:has-text('💾 Save')")
        save_button.click(force=True)

        # Wait for duplicate detection
        page.wait_for_function("""() => {
            const uploadForm = document.querySelector('[x-data="uploadForm()"]');
            if (!uploadForm || !uploadForm._x_dataStack) return false;
            const editor = uploadForm._x_dataStack[0].bottleEditor;
            return editor && editor.showDuplicateDialog === true && editor.duplicates && editor.duplicates.length > 0;
        }""", timeout=10000)

        # Get the vault_path of the first duplicate and call Replace
        result = page.evaluate("""() => {
            const uploadForm = document.querySelector('[x-data="uploadForm()"]');
            const editor = uploadForm._x_dataStack[0].bottleEditor;
            const duplicateVaultPath = editor.duplicates[0].vault_path;
            editor.handleDuplicateResolution('replace', duplicateVaultPath);
            return duplicateVaultPath;
        }""")

        # Wait for replacement to complete
        page.wait_for_timeout(3000)

        # Verify: Still only 1 Weller bottle (replaced, not duplicated)
        # Use specific pattern to match only the simple Weller bottle (not Buffalo Trace Weller)
        weller_bottles = list(whiskey_dir.glob("Weller - THE ORIGINAL*"))

        assert len(weller_bottles) == 1, f"Expected 1 Weller bottle (replaced, not duplicated), found {len(weller_bottles)}: {[b.name for b in weller_bottles]}"

        # No cleanup needed - test_vault fixture recreates the vault for next test

    def test_duplicate_detection_triggers_correctly(self, web_server, sample_image, browser_no_cache, test_vault):
        """
        Test: Duplicate detection triggers and shows dialog.

        This is the most basic test - just verify the detection works.
        """
        page = browser_no_cache.new_page()

        vault_path = test_vault
        whiskey_dir = vault_path / "1_Whiskeys"

        # Verify fixture bottle exists
        fixture_bottle = whiskey_dir / "Weller - THE ORIGINAL WHEATED BOURBON"
        assert fixture_bottle.exists(), f"Fixture bottle not found: {fixture_bottle}"

        # Upload bourbon_001.jpg
        page.goto(f"{web_server}/upload")
        page.click("button:has-text('Single Bottle')")
        page.wait_for_selector("text=How many bottles?", timeout=5000)
        page.set_input_files("input[type='file']", sample_image)
        page.click("text=✓ Upload & Extract")

        # Wait for modal
        page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=60000)

        # Click Save
        save_button = page.locator("button:has-text('💾 Save')")
        save_button.click(force=True)

        # Wait for duplicate dialog to appear
        page.wait_for_function("""() => {
            const uploadForm = document.querySelector('[x-data="uploadForm()"]');
            if (!uploadForm || !uploadForm._x_dataStack) return false;
            const editor = uploadForm._x_dataStack[0].bottleEditor;
            return editor && editor.showDuplicateDialog === true;
        }""", timeout=10000)

        # Verify duplicate detection triggered
        duplicate_data = page.evaluate("""() => {
            const uploadForm = document.querySelector('[x-data="uploadForm()"]');
            if (!uploadForm || !uploadForm._x_dataStack) return null;
            const editor = uploadForm._x_dataStack[0].bottleEditor;
            return {
                showDuplicateDialog: editor.showDuplicateDialog,
                duplicatesCount: editor.duplicates ? editor.duplicates.length : 0,
                duplicates: editor.duplicates || []
            };
        }""")

        assert duplicate_data is not None, "Could not access bottleEditor"
        assert duplicate_data['showDuplicateDialog'] == True, "Duplicate dialog should be visible"
        assert duplicate_data['duplicatesCount'] > 0, f"Expected duplicates to be found, got {duplicate_data['duplicatesCount']}"

        # Cleanup - skip the save
        page.evaluate("""() => {
            const uploadForm = document.querySelector('[x-data="uploadForm()"]');
            uploadForm._x_dataStack[0].bottleEditor.handleDuplicateResolution('skip');
        }""")
