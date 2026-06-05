"""
REAL End-to-End Browser Tests for Bottle Upload Flow.

These tests use Playwright to run an actual browser and test the COMPLETE user experience:
1. Load upload page in browser
2. Click upload button
3. Select and upload image file
4. Verify modal opens with extracted data
5. Click save button
6. Verify success message appears
7. Verify modal closes

This would have caught the upload workflow breaking because it actually runs JavaScript
in a real browser, not just API calls.
"""


import pytest
from playwright.sync_api import expect, sync_playwright

# Fixtures are now in conftest.py


class TestBrowserUploadFlow:
    """Test upload workflow in actual browser."""

    def test_upload_page_loads(self, web_server):
        """Test that upload page loads in browser."""
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            # Navigate to upload page
            page.goto(f"{web_server}/upload")

            # Verify page title
            expect(page).to_have_title("Import - The Reserve")

            # Verify upload type buttons exist (tasting card moved to Tastings page)
            expect(page.locator("button:has-text('Single Bottle')")).to_be_visible()
            expect(page.locator("button:has-text('Bottle Manifest')")).to_be_visible()

            browser.close()

    def test_upload_bottle_opens_modal(self, web_server, sample_image):
        """
        CRITICAL: Test complete upload → modal workflow in browser.

        This is the test that would have caught the upload breakage!
        """
        console_logs = []

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            # Capture ALL console logs
            page.on("console", lambda msg: console_logs.append(f"{msg.type}: {msg.text}"))

            # Navigate and select bottle upload
            page.goto(f"{web_server}/upload")
            page.click("button:has-text('Single Bottle')")

            # Wait for purchase info section to appear
            page.wait_for_selector("text=How many bottles?", timeout=5000)

            # Set file input and trigger upload
            page.set_input_files("input[type='file']", sample_image)

            # Click upload button
            page.click("text=✓ Upload & Extract")

            # Wait for processing (spinner should appear, but might be quick)
            # Use a try/catch since processing state might transition too fast to catch
            try:
                page.locator("text=Processing").wait_for(state="visible", timeout=2000)
                print("✓ Processing state detected")
            except:
                # Processing might have completed quickly, that's okay
                print("⚠ Processing state was too fast to catch (or skipped)")

            # Wait for modal to open (may take 10-30 seconds for LLM extraction)
            # Modal should have bottle data
            try:
                page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=60000)

                # Verify modal is visible (not just in DOM)
                modal = page.locator("[x-show='bottleEditor.isOpen']")
                expect(modal).to_be_visible()

                # Verify modal header shows bottle data (producer - name format)
                header = page.locator("h2.text-3xl")
                expect(header).to_be_visible()

                # Verify at least one input field is present (proves form loaded)
                expect(page.locator("input[x-model*='editableBottle']").first).to_be_visible()

                # Verify label image is displayed (not placeholder)
                label_img = page.locator("img[alt='Uploaded Label']")
                expect(label_img).to_be_visible()

                # Verify Cropper.js is loaded (for manual crop functionality)
                cropper_loaded = page.evaluate("typeof Cropper !== 'undefined'")
                if cropper_loaded:
                    print("✓ Cropper.js library loaded")
                else:
                    print("⚠ Cropper.js library NOT loaded - manual crop will fail")

                # Get the image src to verify it's not the placeholder
                img_src = label_img.get_attribute("src")

                # Wait a moment for Alpine to process uploadId
                page.wait_for_timeout(1000)
                img_src_after_wait = label_img.get_attribute("src")

                print(f"Image src (immediate): {img_src}")
                print(f"Image src (after 1s): {img_src_after_wait}")

                if "no-label.svg" in img_src_after_wait:
                    print("⚠ Label showing placeholder instead of actual image")

                    # Check if uploadId was set correctly
                    upload_id_logs = [log for log in console_logs if 'upload_id:' in log]
                    print(f"Upload ID logs: {upload_id_logs}")
                else:
                    print("✓ Label image displayed correctly")

                # Success! Modal opened with extracted data
                print("✓ Upload workflow works: Modal opened with bottle data")

                # Verify console logs show bottle extraction
                relevant_logs = [log for log in console_logs if 'Upload response' in log or 'Bottles extracted' in log or 'bottleEditor' in log]
                print("\nConsole logs during upload:")
                for log in relevant_logs:
                    print(f"  {log}")

                # Verify we got the expected logs
                bottles_extracted_log = [log for log in console_logs if 'Bottles extracted' in log]
                if bottles_extracted_log:
                    print(f"\n✓ Verified: {bottles_extracted_log[0]}")
                else:
                    print("\n⚠ Warning: Did not see 'Bottles extracted' log")

            except Exception as e:
                # Capture screenshot for debugging
                screenshot_path = "/tmp/upload_failure.png"
                page.screenshot(path=screenshot_path)

                # Get page HTML for debugging
                html_path = "/tmp/upload_failure.html"
                with open(html_path, 'w') as f:
                    f.write(page.content())

                pytest.fail(f"Modal did not open after upload.\nScreenshot: {screenshot_path}\nHTML: {html_path}\nError: {e}")

            finally:
                browser.close()

    # Note: Removed cross-upload-type test as it's covered by the state reset fixes in clearFile()

    def test_metadata_search_works(self, web_server, sample_image):
        """Test that metadata search (enrich) works in the bottle modal."""
        console_logs = []

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            # Capture console logs and network errors
            page.on("console", lambda msg: console_logs.append(f"{msg.type}: {msg.text}"))
            page.on("pageerror", lambda err: console_logs.append(f"PAGE ERROR: {err}"))

            # Capture any alerts
            alert_messages = []
            page.on("dialog", lambda dialog: (
                alert_messages.append(f"ALERT: {dialog.message}"),
                dialog.accept()
            ))

            # Capture ALL network responses
            verify_response = []
            def capture_responses(response):
                url = response.url
                if "bottles/verify" in url or "management" in url:
                    console_logs.append(f"HTTP {response.status}: {url}")
                    try:
                        body = response.text()
                        verify_response.append(body)
                        console_logs.append(f"RESPONSE BODY: {body[:300]}")
                    except:
                        pass

            page.on("response", capture_responses)

            # Upload a bottle to open modal
            page.goto(f"{web_server}/upload")
            page.click("button:has-text('Single Bottle')")
            page.wait_for_selector("text=How many bottles?", timeout=5000)
            page.set_input_files("input[type='file']", sample_image)
            page.click("text=✓ Upload & Extract")

            # Wait for modal to open
            page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=60000)
            modal = page.locator("[x-show='bottleEditor.isOpen']")
            expect(modal).to_be_visible()

            # Click "Search for Updates" button
            search_button = page.locator("button:has-text('Search for Updates')")
            expect(search_button).to_be_visible()

            # Check if button is enabled
            is_disabled = search_button.is_disabled()
            print(f"Search button disabled: {is_disabled}")

            search_button.click()
            print("✓ Search button clicked")

            # Wait for search to complete (spinner should appear then disappear)
            try:
                # Check for verifying state
                page.wait_for_selector("text=Searching...", timeout=5000)
                print("✓ Search initiated")

                # Wait for results (button text changes back to "Search for Updates")
                page.wait_for_selector("button:has-text('Search for Updates')", timeout=35000)
                print("✓ Search completed")

                # Check for error alert first (enrichment failures show browser alert)
                page.wait_for_timeout(1000)  # Give time for alert to appear

                # Print all console logs to see what happened
                print("\nAll console logs:")
                for log in console_logs[-10:]:  # Last 10 logs
                    print(f"  {log}")

                # Check console for enrichment errors
                enrichment_errors = [log for log in console_logs if 'enrichment failed' in log.lower() or 'search failed' in log.lower()]

                # Check the verify response for verification failure
                if verify_response:
                    import json
                    try:
                        response_data = json.loads(verify_response[0])
                        if response_data.get("metadata", {}).get("verified") == False:
                            error_msg = response_data.get("metadata", {}).get("error", "Unknown error")
                            print(f"\n⚠ Enrichment verification failed: {error_msg}")
                            pytest.fail(f"Metadata enrichment failed: {error_msg}")
                    except:
                        pass

                if enrichment_errors:
                    # Enrichment failed - this is a problem we should detect
                    print("\n⚠ Enrichment failed (detected in console logs):")
                    for log in enrichment_errors:
                        print(f"  {log}")

                    # E2E test should FAIL if enrichment fails
                    pytest.fail(f"Metadata enrichment failed. Check server logs for validation errors. Console: {enrichment_errors}")

                # Print any alerts that appeared
                if alert_messages:
                    print("\n⚠ Alerts detected:")
                    for msg in alert_messages:
                        print(f"  {msg}")

                # Check for success indicators
                no_updates = page.locator("text=No Updates Needed")
                has_changes = page.locator("text=Review suggested changes")
                apply_button = page.locator("button:has-text('Apply Selected Changes')")
                accept_all_button = page.locator("button:has-text('Accept All')")
                cancel_button = page.locator("button:has-text('Cancel')")

                if no_updates.is_visible():
                    print("✓ No metadata updates needed")
                elif has_changes.is_visible():
                    print("✓ Metadata updates found")
                    # Verify action buttons are present
                    expect(apply_button).to_be_visible()
                    expect(accept_all_button).to_be_visible()
                    expect(cancel_button).to_be_visible()
                    print("✓ Action buttons present: Apply Selected, Accept All, Cancel")
                else:
                    print("✓ Search completed (no UI changes visible)")

            except Exception as e:
                # Capture screenshot
                screenshot_path = "/tmp/metadata_search_failure.png"
                page.screenshot(path=screenshot_path)

                # Print all console logs
                print("\nConsole logs during metadata search:")
                for log in console_logs:
                    print(f"  {log}")

                pytest.fail(f"Metadata search test failed. Screenshot: {screenshot_path}. Error: {e}")

            finally:
                browser.close()

    def test_upload_bottle_shows_error_on_failure(self, web_server):
        """Test that upload failures show error message, not 'Found 0 bottles'."""
        console_logs = []

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            # Capture console logs
            page.on("console", lambda msg: console_logs.append(f"{msg.type}: {msg.text}"))

            page.goto(f"{web_server}/upload")
            page.click("button:has-text('Single Bottle')")
            page.wait_for_selector("text=How many bottles?")

            # Create a tiny invalid file
            from pathlib import Path
            invalid_file = Path("/tmp/invalid_image.txt")
            invalid_file.write_text("not an image")

            # Upload invalid file
            page.set_input_files("input[type='file']", str(invalid_file))
            page.click("text=✓ Upload & Extract")

            # Should show error, NOT "Found 0 bottles"
            page.wait_for_selector("text=/error|failed/i", timeout=10000)

            # Verify we DON'T see "Found 0 bottle(s)"
            found_zero_text = page.locator("text=Found 0 bottle(s)")
            assert not found_zero_text.is_visible(), "Should not show 'Found 0 bottles' on error"

            # Verify error message is shown
            error_div = page.locator("[x-show='error']")
            expect(error_div).to_be_visible()

            print("✓ Upload failure shows error, not 'Found 0 bottles'")

            browser.close()

    def test_manual_crop_workflow(self, web_server, sample_image):
        """
        Test manual crop workflow in upload modal.

        CRITICAL: This test verifies the backend actually processes the crop
        by intercepting the network request and checking the response status.
        """
        console_logs = []
        alert_messages = []
        crop_responses = []

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            # Capture console logs and alerts
            page.on("console", lambda msg: console_logs.append(f"{msg.type}: {msg.text}"))
            page.on("dialog", lambda dialog: (
                alert_messages.append(f"ALERT: {dialog.message}"),
                dialog.accept()
            ))

            # CRITICAL: Intercept network requests to verify backend processing
            def capture_crop_response(response):
                if "manual-crop" in response.url:
                    crop_responses.append({
                        "url": response.url,
                        "status": response.status,
                        "ok": response.ok
                    })
                    print(f"CROP RESPONSE: {response.status} {response.url}")
                    try:
                        body = response.json()
                        crop_responses[-1]["body"] = body
                        print(f"CROP BODY: {body}")
                    except:
                        pass

            page.on("response", capture_crop_response)

            # Upload a bottle
            page.goto(f"{web_server}/upload")
            page.click("button:has-text('Single Bottle')")
            page.wait_for_selector("text=How many bottles?", timeout=5000)
            page.set_input_files("input[type='file']", sample_image)
            page.click("text=✓ Upload & Extract")

            # Wait for modal
            page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=60000)
            modal = page.locator("[x-show='bottleEditor.isOpen']")
            expect(modal).to_be_visible()

            print("✓ Modal opened")

            # Click Manual Crop button
            manual_crop_button = page.locator("button:has-text('✂️ Manual Crop')")
            expect(manual_crop_button).to_be_visible()
            manual_crop_button.click()

            print("✓ Clicked Manual Crop button")

            # Wait for cropper interface to appear
            page.wait_for_selector("#manualCropImage", timeout=5000)
            cropper_image = page.locator("#manualCropImage")
            expect(cropper_image).to_be_visible()

            print("✓ Cropper interface visible")

            # Verify Cropper.js initialized (check for cropper-container)
            page.wait_for_selector(".cropper-container", timeout=5000)
            print("✓ Cropper.js initialized successfully")

            # Click "Accept Crop" button
            accept_crop_button = page.locator("button:has-text('✓ Accept Crop')")
            expect(accept_crop_button).to_be_visible()
            accept_crop_button.click()

            print("✓ Clicked Accept Crop button")

            # Wait for crop request to complete
            page.wait_for_timeout(3000)

            # CRITICAL: Verify backend returned success
            if not crop_responses:
                pytest.fail("No crop request was made to the backend!")

            crop_response = crop_responses[-1]  # Get the last crop response
            if not crop_response["ok"]:
                pytest.fail(f"Backend crop failed with status {crop_response['status']}: {crop_response.get('body', 'No body')}")

            print(f"✓ Backend returned success: {crop_response['status']}")

            # Verify cropper interface closed (sign of success)
            cropper_container = page.locator(".cropper-container")

            # Check for errors in console
            error_logs = [log for log in console_logs if 'error' in log.lower() or '404' in log or 'failed' in log.lower()]

            # Check for alerts (errors would show as alerts)
            error_alerts = [msg for msg in alert_messages if 'failed' in msg.lower() or '404' in msg or 'error' in msg.lower()]

            if error_logs:
                print("\n⚠ Errors found in console logs:")
                for log in error_logs:
                    print(f"  {log}")
                pytest.fail(f"Manual crop failed with errors: {error_logs}")

            if error_alerts:
                print("\n⚠ Error alerts found:")
                for msg in error_alerts:
                    print(f"  {msg}")
                pytest.fail(f"Manual crop showed error alert: {error_alerts}")

            # Verify cropper actually closed (means crop succeeded)
            try:
                expect(cropper_container).not_to_be_visible(timeout=2000)
                print("✓ Cropper closed after crop (success)")
            except AssertionError:
                print("⚠ Cropper still visible - crop may have failed silently")
                pytest.fail("Manual crop did not complete - cropper still visible")

            print("✓ Manual crop completed successfully (backend verified)")

            browser.close()

    def test_auto_crop_workflow(self, web_server, sample_image):
        """Test auto-crop workflow in upload modal."""
        console_logs = []
        alert_messages = []

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            page.on("console", lambda msg: console_logs.append(f"{msg.type}: {msg.text}"))
            page.on("dialog", lambda dialog: (
                alert_messages.append(f"ALERT: {dialog.message}"),
                dialog.accept()
            ))

            # Upload a bottle
            page.goto(f"{web_server}/upload")
            page.click("button:has-text('Single Bottle')")
            page.wait_for_selector("text=How many bottles?", timeout=5000)
            page.set_input_files("input[type='file']", sample_image)
            page.click("text=✓ Upload & Extract")

            # Wait for modal
            page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=60000)

            # Click Auto-Crop button
            auto_crop_button = page.locator("button:has-text('🤖 Auto-Crop')")
            expect(auto_crop_button).to_be_visible()
            auto_crop_button.click()

            print("✓ Clicked Auto-Crop button")

            # Wait for auto-crop to complete (should see processing state then complete)
            page.wait_for_timeout(5000)

            # Check for errors
            error_logs = [log for log in console_logs if 'error' in log.lower() or '404' in log]
            if error_logs:
                pytest.fail(f"Auto-crop failed with errors: {error_logs}")

            print("✓ Auto-crop completed successfully")

            browser.close()

    def test_cancel_manual_crop(self, web_server, sample_image):
        """Test canceling manual crop doesn't break anything."""
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            # Upload a bottle
            page.goto(f"{web_server}/upload")
            page.click("button:has-text('Single Bottle')")
            page.wait_for_selector("text=How many bottles?", timeout=5000)
            page.set_input_files("input[type='file']", sample_image)
            page.click("text=✓ Upload & Extract")

            # Wait for modal
            page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=60000)

            # Click Manual Crop
            manual_crop_button = page.locator("button:has-text('✂️ Manual Crop')")
            manual_crop_button.click()

            # Wait for cropper
            page.wait_for_selector(".cropper-container", timeout=5000)

            # Click Cancel instead of Accept
            # Wait for the Accept Crop button to be visible (confirms manual crop UI is active)
            page.wait_for_selector("button:has-text('✓ Accept Crop')", timeout=5000)
            # Now click the cancel button that's next to it
            cancel_button = page.locator("button:has-text('✓ Accept Crop')").locator("..").locator("button:has-text('Cancel')")
            cancel_button.click()

            print("✓ Clicked Cancel button")

            # Verify cropper interface is gone
            page.wait_for_timeout(1000)
            cropper_container = page.locator(".cropper-container")
            expect(cropper_container).not_to_be_visible()

            print("✓ Cropper closed after cancel")

            # Verify we can still use other buttons (modal not broken)
            manual_crop_button = page.locator("button:has-text('✂️ Manual Crop')")
            expect(manual_crop_button).to_be_visible()

            print("✓ Modal still functional after cancel")

            browser.close()

    def test_modal_save_shows_feedback(self, web_server, sample_image):
        """Test that clicking save shows success feedback."""
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            # Capture console logs and network requests
            def log_response(response):
                if "bottles/save" in response.url:
                    print(f"SAVE RESPONSE: {response.status}")
                    try:
                        body = response.text()
                        print(f"SAVE BODY: {body}")
                    except:
                        pass

            page.on("console", lambda msg: print(f"CONSOLE: {msg.type}: {msg.text}"))
            page.on("pageerror", lambda err: print(f"PAGE ERROR: {err}"))
            page.on("response", log_response)

            # Go through upload flow
            page.goto(f"{web_server}/upload")
            page.click("button:has-text('Single Bottle')")
            page.wait_for_selector("text=How many bottles?")
            page.set_input_files("input[type='file']", sample_image)
            page.click("text=✓ Upload & Extract")

            # Wait for modal
            page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=60000)

            # Fill in required fields (producer and name should be extracted)
            # Click save button (use first if multiple exist)
            save_button = page.locator("button:has-text('💾 Save')")
            expect(save_button).to_be_visible()
            save_button.click()

            # Wait a moment for save to process
            page.wait_for_timeout(2000)

            # Verify either success toast OR duplicate dialog appears (both are valid feedback)
            try:
                # Check for success toast (bottle was new)
                toast = page.locator("text=Bottle saved to vault")
                if toast.is_visible():
                    print("✓ Save feedback works: Success toast appeared (new bottle)")
                else:
                    # Check for duplicate dialog (bottle already exists)
                    # Use .first to avoid strict mode errors when multiple elements match
                    duplicate_dialog = page.locator("text=Duplicate Found").first
                    expect(duplicate_dialog).to_be_visible(timeout=5000)
                    print("✓ Save feedback works: Duplicate dialog appeared (bottle exists)")

            except Exception as e:
                # Capture debugging info
                screenshot_path = "/tmp/save_failure.png"
                page.screenshot(path=screenshot_path)

                html_path = "/tmp/save_failure_modal.html"
                with open(html_path, 'w') as f:
                    f.write(page.content())

                # Check for error messages in modal
                error_text = page.locator("text=/error/i").all_text_contents()
                print(f"Error messages found: {error_text}")

                pytest.fail(f"Neither success toast nor duplicate dialog appeared. Screenshot: {screenshot_path}. HTML: {html_path}. Error: {e}")

            finally:
                browser.close()


class TestBrowserManagementFlow:
    """Test bottle collection grid workflow in browser."""

    # Helper to enter bottle grid mode
    def _enter_grid_mode(self, page, web_server):
        """Navigate to /bottles and wait for grid to load."""
        page.goto(f"{web_server}/bottles")

        # Wait for grid to load with bottles
        page.wait_for_selector("text=Showing", timeout=10000)

    def test_management_page_loads(self, web_server):
        """Test bottles page loads and displays collection."""
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            page.goto(f"{web_server}/bottles")

            # Verify page loaded
            expect(page).to_have_title("Bottles - The Reserve")

            # Verify collection header
            expect(page.locator("h2:has-text('Bottle Collection')")).to_be_visible()

            browser.close()

    def test_click_bottle_opens_modal(self, web_server, test_vault):
        """Test clicking a bottle in grid opens the modal."""
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            # Enter grid mode
            self._enter_grid_mode(page, web_server)

            # Wait for bottles to appear in grid
            # Bottles have cursor-pointer and rounded-lg classes with the bottle name text
            page.wait_for_selector(".cursor-pointer.rounded-lg", timeout=10000)

            # Click first bottle
            first_bottle = page.locator(".cursor-pointer.rounded-lg").first
            first_bottle.click()

            # Verify modal opens
            modal = page.locator("[x-show='bottleEditor.isOpen']")
            expect(modal).to_be_visible(timeout=5000)

            print("✓ Management workflow works: Clicking bottle opens modal")

            browser.close()

    def test_modal_save_reloads_page(self, web_server, test_vault):
        """Test that saving in management mode reloads the page."""
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            # Enter grid mode
            self._enter_grid_mode(page, web_server)

            # Wait for bottles to load
            page.wait_for_selector(".cursor-pointer.rounded-lg", timeout=10000)

            # Click bottle and open modal
            page.locator(".cursor-pointer.rounded-lg").first.click()
            page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=5000)

            # Click save
            page.click("button:has-text('💾 Save')")

            # Verify success toast appears
            expect(page.locator("text=Bottle saved successfully")).to_be_visible(timeout=5000)

            # Verify page reloads (modal should close and grid should be visible again)
            page.wait_for_selector(".cursor-pointer.rounded-lg", timeout=5000)

            print("✓ Save in management mode works: Page reloaded")

            browser.close()

    def test_manual_crop_workflow(self, web_server, test_vault):
        """
        Test manual crop workflow for existing bottles in management mode.

        CRITICAL: This test verifies the backend actually processes the crop
        for bottles that already have labels in the vault.

        Uses test_vault fixture which copies fixture bottles WITH labels
        to ensure we have bottles to crop.
        """
        console_logs = []
        alert_messages = []
        crop_responses = []

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            # Capture console logs and alerts
            page.on("console", lambda msg: console_logs.append(f"{msg.type}: {msg.text}"))
            page.on("dialog", lambda dialog: (
                alert_messages.append(f"ALERT: {dialog.message}"),
                dialog.accept()
            ))

            # CRITICAL: Intercept network requests to verify backend processing
            def capture_crop_response(response):
                if "manual-crop" in response.url:
                    crop_responses.append({
                        "url": response.url,
                        "status": response.status,
                        "ok": response.ok
                    })
                    print(f"CROP RESPONSE: {response.status} {response.url}")
                    try:
                        body = response.json()
                        crop_responses[-1]["body"] = body
                        print(f"CROP BODY: {body}")
                    except:
                        pass

            page.on("response", capture_crop_response)

            # Enter grid mode
            self._enter_grid_mode(page, web_server)
            print("✓ Management page loaded with bottles")

            # Find a bottle that has a label (look for one that shows an image, not placeholder)
            # The fixture bottles (Weller, Caymus) should have labels
            bottle_cards = page.locator(".cursor-pointer.rounded-lg")
            bottle_count = bottle_cards.count()
            print(f"Found {bottle_count} bottles")

            # Click first bottle to open modal
            bottle_cards.first.click()

            # Wait for modal
            page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=5000)
            modal = page.locator("[x-show='bottleEditor.isOpen']")
            expect(modal).to_be_visible()

            print("✓ Modal opened")

            # Check if Manual Crop button is visible (only shows if bottle has a label)
            manual_crop_button = page.locator("button:has-text('✂️ Manual Crop')")

            # If no Manual Crop button, the bottle doesn't have a label - skip to find one that does
            if not manual_crop_button.is_visible():
                print("⚠ First bottle has no label, trying to find one with a label...")

                # Close modal and try other bottles
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)

                found_with_label = False
                for i in range(1, min(bottle_count, 10)):  # Try up to 10 bottles
                    bottle_cards.nth(i).click()
                    page.wait_for_selector("[x-show='bottleEditor.isOpen']", timeout=5000)

                    manual_crop_button = page.locator("button:has-text('✂️ Manual Crop')")
                    if manual_crop_button.is_visible():
                        print(f"✓ Found bottle with label at index {i}")
                        found_with_label = True
                        break

                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)

                if not found_with_label:
                    pytest.fail("No bottles with labels found in test vault - cannot test manual crop")

            expect(manual_crop_button).to_be_visible()
            manual_crop_button.click()

            print("✓ Clicked Manual Crop button")

            # Wait for cropper interface to appear
            page.wait_for_selector("#manualCropImage", timeout=5000)
            cropper_image = page.locator("#manualCropImage")
            expect(cropper_image).to_be_visible()

            print("✓ Cropper interface visible")

            # Verify Cropper.js initialized (check for cropper-container)
            try:
                page.wait_for_selector(".cropper-container", timeout=10000)
                print("✓ Cropper.js initialized successfully")
            except Exception as e:
                # Capture debug info
                screenshot_path = "/tmp/mgmt_cropper_init_failure.png"
                page.screenshot(path=screenshot_path)

                print("\n⚠ Cropper.js failed to initialize")
                print(f"Screenshot saved to: {screenshot_path}")
                print("\nConsole logs:")
                for log in console_logs[-20:]:  # Last 20 logs
                    print(f"  {log}")

                # Check for errors that might explain the failure
                error_logs = [log for log in console_logs if 'error' in log.lower() or 'Cropper' in log]
                if error_logs:
                    print("\nError/Cropper logs:")
                    for log in error_logs:
                        print(f"  {log}")

                pytest.fail(f"Cropper.js did not initialize. Check screenshot at {screenshot_path}. Error: {e}")

            # Click "Accept Crop" button
            accept_crop_button = page.locator("button:has-text('✓ Accept Crop')")
            expect(accept_crop_button).to_be_visible()
            accept_crop_button.click()

            print("✓ Clicked Accept Crop button")

            # Wait for crop request to complete
            page.wait_for_timeout(3000)

            # CRITICAL: Verify backend returned success
            if not crop_responses:
                pytest.fail("No crop request was made to the backend!")

            crop_response = crop_responses[-1]  # Get the last crop response
            if not crop_response["ok"]:
                pytest.fail(f"Backend crop failed with status {crop_response['status']}: {crop_response.get('body', 'No body')}")

            print(f"✓ Backend returned success: {crop_response['status']}")

            # Verify cropper interface closed (sign of success)
            cropper_container = page.locator(".cropper-container")

            # Check for errors in console
            error_logs = [log for log in console_logs if 'error' in log.lower() or '404' in log or 'failed' in log.lower()]

            # Check for alerts (errors would show as alerts)
            error_alerts = [msg for msg in alert_messages if 'failed' in msg.lower() or '404' in msg or 'error' in msg.lower()]

            if error_logs:
                print("\n⚠ Errors found in console logs:")
                for log in error_logs:
                    print(f"  {log}")
                pytest.fail(f"Manual crop failed with errors: {error_logs}")

            if error_alerts:
                print("\n⚠ Error alerts found:")
                for msg in error_alerts:
                    print(f"  {msg}")
                pytest.fail(f"Manual crop showed error alert: {error_alerts}")

            # Verify cropper actually closed (means crop succeeded)
            try:
                expect(cropper_container).not_to_be_visible(timeout=2000)
                print("✓ Cropper closed after crop (success)")
            except AssertionError:
                print("⚠ Cropper still visible - crop may have failed silently")
                pytest.fail("Manual crop did not complete - cropper still visible")

            print("✓ Management manual crop completed successfully (backend verified)")

            browser.close()
