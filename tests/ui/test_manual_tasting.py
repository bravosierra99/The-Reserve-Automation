"""Tests for the manual tasting save endpoint.

The manual tasting wizard manages ALL state in Alpine.js and POSTs a single
payload to /api/v1/manual-tasting/save. If this endpoint breaks, users see
a spinner forever or a 500 with no recovery path.

These tests cover the save happy path and the error branches that currently
have no test coverage.
"""

from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _obsidian_payload(bottle_id: str, **kwargs) -> dict:
    base = {
        "mode": "obsidian",
        "selected_bottle_id": bottle_id,
        "taster_name": "Alice",
        "tasting_date": "2026-04-23",
        "beverage_type": "whiskey",
        "tasting_data": {
            "whiskey_nose": 2.5,
            "whiskey_palate": 2.8,
            "whiskey_finish": 2.0,
            "whiskey_overall": 0.8,
            "overall_notes": "Rich and complex",
        },
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestManualTastingSaveHappyPath:
    def test_save_obsidian_mode_returns_200(self, ui_client, seeded_bottles):
        bottle_id = str(seeded_bottles["whiskey_id"])
        with patch(
            "reserve_automation.web.routes.tastings.TastingService.save_manual_tasting_direct",
            new_callable=AsyncMock,
            return_value=(True, "/data/tastings/test.md", None),
        ):
            resp = ui_client.post(
                "/api/v1/manual-tasting/save",
                json=_obsidian_payload(bottle_id),
            )
        assert resp.status_code == 200, resp.text

    def test_save_response_has_status_field(self, ui_client, seeded_bottles):
        bottle_id = str(seeded_bottles["whiskey_id"])
        with patch(
            "reserve_automation.web.routes.tastings.TastingService.save_manual_tasting_direct",
            new_callable=AsyncMock,
            return_value=(True, "/data/tastings/test.md", None),
        ):
            data = ui_client.post(
                "/api/v1/manual-tasting/save",
                json=_obsidian_payload(bottle_id),
            ).json()
        assert data.get("status") == "saved", (
            "Response must contain {'status': 'saved'}; "
            "frontend checks this to show success toast"
        )


# ---------------------------------------------------------------------------
# Validation error paths
# ---------------------------------------------------------------------------

class TestManualTastingSaveValidation:
    def test_missing_taster_name_returns_400(self, ui_client, seeded_bottles):
        payload = _obsidian_payload(str(seeded_bottles["whiskey_id"]))
        payload["taster_name"] = ""
        resp = ui_client.post("/api/v1/manual-tasting/save", json=payload)
        assert resp.status_code == 400
        assert "taster" in resp.json()["detail"].lower()

    def test_missing_tasting_date_returns_400(self, ui_client, seeded_bottles):
        payload = _obsidian_payload(str(seeded_bottles["whiskey_id"]))
        payload["tasting_date"] = ""
        resp = ui_client.post("/api/v1/manual-tasting/save", json=payload)
        assert resp.status_code == 400
        assert "date" in resp.json()["detail"].lower()

    def test_missing_bottle_returns_400(self, ui_client):
        payload = {
            "mode": "obsidian",
            "taster_name": "Alice",
            "tasting_date": "2026-04-23",
            "beverage_type": "whiskey",
            "tasting_data": {},
        }
        resp = ui_client.post("/api/v1/manual-tasting/save", json=payload)
        assert resp.status_code in (400, 422), (
            "Missing bottle ID must return 400/422, not silently succeed"
        )

    def test_nonexistent_bottle_id_returns_404(self, ui_client):
        payload = _obsidian_payload("999999")
        with patch(
            "reserve_automation.web.routes.tastings.TastingService.save_manual_tasting_direct",
            new_callable=AsyncMock,
            return_value=(True, "/data/tastings/test.md", None),
        ):
            resp = ui_client.post("/api/v1/manual-tasting/save", json=payload)
        assert resp.status_code == 404, (
            "Unknown bottle ID must return 404; currently may silently save with wrong bottle"
        )


# ---------------------------------------------------------------------------
# Service error propagation
# ---------------------------------------------------------------------------

class TestManualTastingSaveServiceErrors:
    def test_service_failure_returns_500_not_200(self, ui_client, seeded_bottles):
        """If TastingService.save fails, the endpoint must not return 200."""
        payload = _obsidian_payload(str(seeded_bottles["whiskey_id"]))
        with patch(
            "reserve_automation.web.routes.tastings.TastingService.save_manual_tasting_direct",
            new_callable=AsyncMock,
            return_value=(False, None, "DB write failed"),
        ):
            resp = ui_client.post("/api/v1/manual-tasting/save", json=payload)
        assert resp.status_code == 500, (
            "A failed save must return 500; currently may return 200 with error buried in body"
        )

    def test_service_exception_returns_500_not_crash(self, ui_client, seeded_bottles):
        """Unhandled exception in TastingService must not crash the process."""
        payload = _obsidian_payload(str(seeded_bottles["whiskey_id"]))
        with patch(
            "reserve_automation.web.routes.tastings.TastingService.save_manual_tasting_direct",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Unexpected DB error"),
        ):
            resp = ui_client.post("/api/v1/manual-tasting/save", json=payload)
        assert resp.status_code == 500
        assert "detail" in resp.json()


# ---------------------------------------------------------------------------
# Event mode save
# ---------------------------------------------------------------------------

class TestManualTastingEventMode:
    def test_event_mode_requires_event_id(self, ui_client, seeded_bottles):
        payload = {
            "mode": "event",
            "selected_bottle_id": str(seeded_bottles["whiskey_id"]),
            "taster_name": "Bob",
            "tasting_date": "2026-04-23",
            "beverage_type": "whiskey",
            "tasting_data": {},
        }
        resp = ui_client.post("/api/v1/manual-tasting/save", json=payload)
        assert resp.status_code == 400
        assert "event" in resp.json()["detail"].lower()

    def test_event_mode_requires_participant_id(self, ui_client, seeded_bottles):
        payload = {
            "mode": "event",
            "event_id": "some-event-id",
            "selected_bottle_id": str(seeded_bottles["whiskey_id"]),
            "taster_name": "Bob",
            "tasting_date": "2026-04-23",
            "beverage_type": "whiskey",
            "tasting_data": {},
        }
        resp = ui_client.post("/api/v1/manual-tasting/save", json=payload)
        assert resp.status_code == 400
        assert "participant" in resp.json()["detail"].lower()
