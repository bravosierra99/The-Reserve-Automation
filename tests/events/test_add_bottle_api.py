"""
Tests for adding bottles to an in-progress event and blind-event redaction.

Covers:
- POST /api/v1/events/{event_id}/bottles (standard + blind auto-numbering)
- Server-side blind redaction in GET /api/v1/events and /api/v1/events/{id}
- Guest-role participant flow (manual-tasting wizard + event tasting save)

Guest role is simulated via the dev-mode `dev_role_override` cookie
(see web/auth/middleware.py _get_dev_user).
"""

GUEST = {"dev_role_override": "guest"}


def _create_event(test_client, bottles, *, is_blind=False, blind_numbers=None,
                  name="Add Bottle Test", beverage_type="whiskey"):
    """Create an event and return its JSON."""
    response = test_client.post(
        "/api/v1/events",
        json={
            "name": name,
            "beverage_type": beverage_type,
            "is_blind": is_blind,
            "host_name": "Test Host",
            "bottle_ids": [b["id"] for b in bottles],
            "blind_numbers": blind_numbers,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestAddBottleToEvent:
    """POST /api/v1/events/{event_id}/bottles"""

    def test_add_bottle_standard_event(self, test_client, weller_bottle, blantons_bottle):
        event = _create_event(test_client, [weller_bottle])

        response = test_client.post(
            f"/api/v1/events/{event['event_id']}/bottles",
            json={"bottle_id": blantons_bottle["id"]},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["bottle"]["bottle_name"] == blantons_bottle["name"]
        assert data["bottle"]["blind_number"] is None

        # Event now has both bottles
        event_after = test_client.get(f"/api/v1/events/{event['event_id']}").json()
        assert len(event_after["bottles"]) == 2
        assert {b["bottle_id"] for b in event_after["bottles"]} == {
            weller_bottle["id"], blantons_bottle["id"]
        }

    def test_add_bottle_blind_auto_number(self, test_client, caymus_bottle, opus_bottle):
        event = _create_event(
            test_client, [caymus_bottle], is_blind=True, blind_numbers=[1],
            beverage_type="wine",
        )

        response = test_client.post(
            f"/api/v1/events/{event['event_id']}/bottles",
            json={"bottle_id": opus_bottle["id"]},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        # Next unused number is assigned automatically
        assert data["bottle"]["blind_number"] == 2
        # Response must not leak the bottle identity while the event is blind+open
        assert data["bottle"]["bottle_name"] == "Bottle #2"
        assert opus_bottle["name"] not in response.text

    def test_add_bottle_blind_explicit_number(self, test_client, caymus_bottle, opus_bottle):
        event = _create_event(
            test_client, [caymus_bottle], is_blind=True, blind_numbers=[1],
            beverage_type="wine",
        )

        response = test_client.post(
            f"/api/v1/events/{event['event_id']}/bottles",
            json={"bottle_id": opus_bottle["id"], "blind_number": 7},
        )
        assert response.status_code == 200, response.text
        assert response.json()["bottle"]["blind_number"] == 7

    def test_add_bottle_blind_number_conflict(self, test_client, caymus_bottle, opus_bottle):
        event = _create_event(
            test_client, [caymus_bottle], is_blind=True, blind_numbers=[1],
            beverage_type="wine",
        )

        response = test_client.post(
            f"/api/v1/events/{event['event_id']}/bottles",
            json={"bottle_id": opus_bottle["id"], "blind_number": 1},
        )
        assert response.status_code == 400
        assert "already taken" in response.json()["detail"].lower()

    def test_add_duplicate_bottle_rejected(self, test_client, weller_bottle):
        event = _create_event(test_client, [weller_bottle])

        response = test_client.post(
            f"/api/v1/events/{event['event_id']}/bottles",
            json={"bottle_id": weller_bottle["id"]},
        )
        assert response.status_code == 409
        assert "already" in response.json()["detail"].lower()

    def test_add_bottle_to_closed_event_rejected(self, test_client, weller_bottle, blantons_bottle):
        event = _create_event(test_client, [weller_bottle])
        test_client.put(f"/api/v1/events/{event['event_id']}/close")

        response = test_client.post(
            f"/api/v1/events/{event['event_id']}/bottles",
            json={"bottle_id": blantons_bottle["id"]},
        )
        assert response.status_code == 400
        assert "closed" in response.json()["detail"].lower()

    def test_add_bottle_event_not_found(self, test_client, weller_bottle):
        response = test_client.post(
            "/api/v1/events/nonexistent-id/bottles",
            json={"bottle_id": weller_bottle["id"]},
        )
        assert response.status_code == 404

    def test_add_bottle_bottle_not_found(self, test_client, weller_bottle):
        event = _create_event(test_client, [weller_bottle])

        response = test_client.post(
            f"/api/v1/events/{event['event_id']}/bottles",
            json={"bottle_id": "99999"},
        )
        assert response.status_code == 404
        assert "bottle not found" in response.json()["detail"].lower()

    def test_add_bottle_non_numeric_id(self, test_client, weller_bottle):
        event = _create_event(test_client, [weller_bottle])

        response = test_client.post(
            f"/api/v1/events/{event['event_id']}/bottles",
            json={"bottle_id": "not-a-number"},
        )
        assert response.status_code == 404

    def test_guest_can_add_bottle(self, test_client, weller_bottle, blantons_bottle):
        """events.participate includes guests — a friend can add their own bottle."""
        event = _create_event(test_client, [weller_bottle])

        response = test_client.post(
            f"/api/v1/events/{event['event_id']}/bottles",
            json={"bottle_id": blantons_bottle["id"]},
            cookies=GUEST,
        )
        assert response.status_code == 200, response.text


class TestBlindRedaction:
    """Blind open events must not leak bottle names to non-managers."""

    def test_guest_sees_redacted_names_on_blind_open_event(
        self, test_client, caymus_bottle, opus_bottle
    ):
        event = _create_event(
            test_client, [caymus_bottle, opus_bottle], is_blind=True,
            blind_numbers=[1, 2], beverage_type="wine",
        )

        response = test_client.get(f"/api/v1/events/{event['event_id']}", cookies=GUEST)
        assert response.status_code == 200
        names = {b["bottle_name"] for b in response.json()["bottles"]}
        assert names == {"Bottle #1", "Bottle #2"}
        assert caymus_bottle["name"] not in response.text
        assert opus_bottle["name"] not in response.text

    def test_admin_sees_real_names_on_blind_open_event(
        self, test_client, caymus_bottle, opus_bottle
    ):
        event = _create_event(
            test_client, [caymus_bottle, opus_bottle], is_blind=True,
            blind_numbers=[1, 2], beverage_type="wine",
        )

        response = test_client.get(f"/api/v1/events/{event['event_id']}")
        assert response.status_code == 200
        names = {b["bottle_name"] for b in response.json()["bottles"]}
        assert names == {caymus_bottle["name"], opus_bottle["name"]}

    def test_guest_sees_real_names_after_reveal(self, test_client, caymus_bottle):
        event = _create_event(
            test_client, [caymus_bottle], is_blind=True, blind_numbers=[1],
            beverage_type="wine",
        )
        test_client.put(f"/api/v1/events/{event['event_id']}/reveal")

        response = test_client.get(f"/api/v1/events/{event['event_id']}", cookies=GUEST)
        assert response.status_code == 200
        assert response.json()["bottles"][0]["bottle_name"] == caymus_bottle["name"]

    def test_guest_sees_real_names_on_non_blind_event(self, test_client, weller_bottle):
        event = _create_event(test_client, [weller_bottle])

        response = test_client.get(f"/api/v1/events/{event['event_id']}", cookies=GUEST)
        assert response.status_code == 200
        assert response.json()["bottles"][0]["bottle_name"] == weller_bottle["name"]

    def test_event_list_redacts_blind_open_events_for_guest(
        self, test_client, caymus_bottle
    ):
        event = _create_event(
            test_client, [caymus_bottle], is_blind=True, blind_numbers=[1],
            beverage_type="wine", name="List Redaction Test",
        )

        response = test_client.get("/api/v1/events", cookies=GUEST)
        assert response.status_code == 200
        listed = next(e for e in response.json() if e["event_id"] == event["event_id"])
        assert listed["bottles"][0]["bottle_name"] == "Bottle #1"


class TestGuestParticipantFlow:
    """A guest (any Google login) must be able to record event tastings."""

    def test_guest_can_open_manual_tasting_page(self, test_client):
        response = test_client.get("/manual-tasting", cookies=GUEST)
        assert response.status_code == 200

    def test_guest_can_save_event_tasting(self, test_client, weller_bottle):
        event = _create_event(test_client, [weller_bottle])

        join = test_client.post(
            f"/api/v1/events/{event['event_id']}/join",
            json={"participant_name": "Guest Friend"},
            cookies=GUEST,
        )
        assert join.status_code == 200, join.text
        participant_id = join.json()["participant_id"]

        response = test_client.post(
            "/api/v1/manual-tasting/save",
            json={
                "mode": "event",
                "beverage_type": "whiskey",
                "taster_name": "Guest Friend",
                "tasting_date": "2026-07-02",
                "selected_bottle_id": weller_bottle["id"],
                "event_id": event["event_id"],
                "participant_id": participant_id,
                "tasting_data": {"Nose": 5, "Taste": 6, "Finish": 5, "Balance": 6},
            },
            cookies=GUEST,
        )
        assert response.status_code == 200, response.text

    def test_guest_cannot_save_obsidian_tasting(self, test_client, weller_bottle):
        """Personal (non-event) tastings stay admin/family only."""
        response = test_client.post(
            "/api/v1/manual-tasting/save",
            json={
                "mode": "obsidian",
                "beverage_type": "whiskey",
                "taster_name": "Sneaky Guest",
                "tasting_date": "2026-07-02",
                "selected_bottle_id": weller_bottle["id"],
                "tasting_data": {"Nose": 5},
            },
            cookies=GUEST,
        )
        assert response.status_code == 403
