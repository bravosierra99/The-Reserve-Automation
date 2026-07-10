"""Contract fixtures for the event system.

Runs the real event lifecycle end-to-end — create a blind whiskey event, two
guests join, each saves tastings through the manual-tasting wizard's exact
payload, host closes and reveals — and snapshots every response shape the
frontend consumes:

    event_create_response        POST /api/v1/events        (event-create.js)
    event_join_response          POST /api/v1/events/{id}/join (event-detail.js)
    manual_tasting_save_response POST /api/v1/manual-tasting/save (manual-tasting.js)
    event_detail_blind_open      GET /api/v1/events/{id} while blind+open
                                 (event-detail.js — redacted bottle names)
    event_detail                 GET /api/v1/events/{id} after reveal
                                 (event-results.js — THE fixture that would
                                 have caught the July 2026 undefined-results bug)
    event_detail_wine            GET /api/v1/events/{id} for a revealed WINE
                                 event — wine scoring/notes are a separate
                                 results-rendering path (the wizard stores wine
                                 aroma/taste/aftertaste notes under
                                 nose/palate/finish_notes)
    events_list                  GET /api/v1/events         (events-page.js,
                                 management-app.js)
    event_bottle_search          GET /api/v1/bottles/search?q=&beverage_type=
                                 (event-detail.js searchBottlesToAdd — NOTE:
                                 MatchCandidate carries the DB id in
                                 bottle_path; there is no bottle_id field)
    event_add_bottle_response    POST /api/v1/events/{id}/bottles on a BLIND
                                 open event (event-detail.js addBottleToEvent)
                                 — identity-redacted: bottle_name is
                                 "Bottle #N" and there is NO bottle_path key
    event_add_bottle_response_open  same POST on a NON-blind event — full
                                 EventBottle echo (bottle_path present,
                                 blind_number null)

The add-bottle events are created AFTER the events_list capture so every
pre-existing fixture above stays byte-identical.

Score design (whiskey /10 = nose/3 + palate/3 + finish/3 + overall/1), chosen
so rankings are unambiguous and JS tests can assert them:
    bottle 1 (Willett):  Alice 9, Bob 8  -> avg 8.5, rank 1
    bottle 2 (Weller):   Alice 7         -> avg 7.0, rank 2
    bottle 3 (Blantons): Bob 4           -> avg 4.0, rank 3
"""

import pytest

from .contract import assert_contract

GUEST = {"dev_role_override": "guest"}

# The wizard initializes every key and sends the full object (see
# manual-tasting.js tastingData) — whiskey tastings still carry wine_* zeros.
def _wizard_tasting_data(nose, palate, finish, overall, *, nose_notes,
                         palate_notes, finish_notes, overall_notes):
    return {
        "wine_appearance": 0,
        "wine_aroma": 0,
        "wine_taste": 0,
        "wine_aftertaste": 0,
        "wine_overall": 0,
        "whiskey_nose": nose,
        "whiskey_palate": palate,
        "whiskey_finish": finish,
        "whiskey_overall": overall,
        "appearance_notes": [],
        "nose_notes": nose_notes,
        "palate_notes": palate_notes,
        "finish_notes": finish_notes,
        "overall_notes": overall_notes,
    }


def _wizard_save_payload(event_id, participant_id, taster, bottle_id, data):
    # Mirrors manual-tasting.js saveRequest exactly: the DB bottle id is sent
    # in BOTH fields (search candidates carry it in bottle_path).
    return {
        "mode": "event",
        "beverage_type": "whiskey",
        "taster_name": taster,
        "tasting_date": "2026-07-07",
        "selected_bottle_id": str(bottle_id),
        "selected_bottle_path": str(bottle_id),
        "event_id": event_id,
        "participant_id": participant_id,
        "tasting_data": data,
    }


@pytest.fixture(scope="module")
def event_flow(contract_client, contract_db):
    """Run the full event lifecycle once; return every captured response."""
    from reserve_automation.core.models import BottleMetadata
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository

    repo = SQLiteBottleRepository(contract_db)
    bottles = [
        repo.create(BottleMetadata(
            producer="Willett", name="Family Estate Single Barrel",
            type="whiskey", source="test", proof=124, region="Kentucky",
            inventory=1,
        )),
        repo.create(BottleMetadata(
            producer="Buffalo Trace", name="Weller Special Reserve",
            type="whiskey", source="test", proof=90, region="Kentucky",
            inventory=1,
        )),
        repo.create(BottleMetadata(
            producer="Blantons", name="Original Single Barrel",
            type="whiskey", source="test", proof=93, region="Kentucky",
            inventory=1,
        )),
    ]
    captured = {}

    create = contract_client.post("/api/v1/events", json={
        "name": "Contract Whiskey Night",
        "beverage_type": "whiskey",
        "is_blind": True,
        "host_name": "Ben",
        "bottle_ids": [str(b.id) for b in bottles],
        "blind_numbers": [1, 2, 3],
    })
    assert create.status_code == 200, create.text
    captured["event_create_response"] = create.json()
    event_id = create.json()["event_id"]

    joins = {}
    for guest in ("Alice", "Bob"):
        join = contract_client.post(
            f"/api/v1/events/{event_id}/join",
            json={"participant_name": guest},
            cookies=GUEST,
        )
        assert join.status_code == 200, join.text
        joins[guest] = join.json()
    captured["event_join_response"] = joins["Alice"]

    blind_open = contract_client.get(f"/api/v1/events/{event_id}", cookies=GUEST)
    assert blind_open.status_code == 200, blind_open.text
    captured["event_detail_blind_open"] = blind_open.json()

    tastings = [
        ("Alice", bottles[0].id, _wizard_tasting_data(
            3, 3, 2, 1,
            nose_notes=["caramel", "oak"], palate_notes=["cherry", "baking spice"],
            finish_notes=["long", "warm"], overall_notes="Outstanding pour")),
        ("Alice", bottles[1].id, _wizard_tasting_data(
            2, 2, 2, 1,
            nose_notes=["vanilla"], palate_notes=["soft wheat"],
            finish_notes=["medium"], overall_notes="Solid daily sipper")),
        ("Bob", bottles[0].id, _wizard_tasting_data(
            2, 3, 3, 0,
            nose_notes=["leather"], palate_notes=["dark fruit"],
            finish_notes=["oily"], overall_notes="")),
        ("Bob", bottles[2].id, _wizard_tasting_data(
            1, 1, 2, 0,
            nose_notes=["ethanol"], palate_notes=["thin"],
            finish_notes=["short"], overall_notes="Not for me")),
    ]
    for taster, bottle_id, data in tastings:
        save = contract_client.post(
            "/api/v1/manual-tasting/save",
            json=_wizard_save_payload(
                event_id, joins[taster]["participant_id"], taster, bottle_id, data,
            ),
            cookies=GUEST,
        )
        assert save.status_code == 200, save.text
        captured["manual_tasting_save_response"] = save.json()

    # Reveal must happen while the event is still open (a closed event can't
    # be revealed); both are PUTs — matches management-app.js.
    assert contract_client.put(f"/api/v1/events/{event_id}/reveal").status_code == 200
    assert contract_client.put(f"/api/v1/events/{event_id}/close").status_code == 200

    detail = contract_client.get(f"/api/v1/events/{event_id}")
    assert detail.status_code == 200, detail.text
    captured["event_detail"] = detail.json()

    # --- Wine event: separate results-rendering path (AWS /20 scoring; the
    # wizard stores wine aroma/taste/aftertaste notes under
    # nose/palate/finish_notes and adds appearance_notes).
    wine_bottles = [
        repo.create(BottleMetadata(
            producer="Caymus Vineyards", name="Cabernet Sauvignon",
            type="wine", source="test", year=2021,
            variety="Cabernet Sauvignon", region="USA - Napa Valley",
            abv=14.5, inventory=1,
        )),
        repo.create(BottleMetadata(
            producer="Opus One", name="Opus One",
            type="wine", source="test", year=2019,
            variety="Bordeaux Blend", region="USA - Napa Valley",
            abv=14.5, inventory=1,
        )),
    ]
    wine_create = contract_client.post("/api/v1/events", json={
        "name": "Contract Wine Night",
        "beverage_type": "wine",
        "is_blind": True,
        "host_name": "Ben",
        "bottle_ids": [str(b.id) for b in wine_bottles],
        "blind_numbers": [1, 2],
    })
    assert wine_create.status_code == 200, wine_create.text
    wine_event_id = wine_create.json()["event_id"]

    wine_join = contract_client.post(
        f"/api/v1/events/{wine_event_id}/join",
        json={"participant_name": "Alice"},
        cookies=GUEST,
    )
    assert wine_join.status_code == 200, wine_join.text

    wine_save = contract_client.post(
        "/api/v1/manual-tasting/save",
        json={
            "mode": "event",
            "beverage_type": "wine",
            "taster_name": "Alice",
            "tasting_date": "2026-07-07",
            "selected_bottle_id": str(wine_bottles[0].id),
            "selected_bottle_path": str(wine_bottles[0].id),
            "event_id": wine_event_id,
            "participant_id": wine_join.json()["participant_id"],
            "tasting_data": {
                # AWS /20: appearance/3 + aroma/6 + taste/6 + aftertaste/3
                # + overall/2 — this one totals 14.5
                "wine_appearance": 2,
                "wine_aroma": 5,
                "wine_taste": 4,
                "wine_aftertaste": 2,
                "wine_overall": 1.5,
                "whiskey_nose": 0,
                "whiskey_palate": 0,
                "whiskey_finish": 0,
                "whiskey_overall": 0,
                "appearance_notes": ["ruby", "clear"],
                "nose_notes": ["cherry", "oak"],
                "palate_notes": ["plum"],
                "finish_notes": ["long"],
                # Deliberately HTML-hostile: the results modal must escape it
                "overall_notes": "lovely & <bold>",
            },
        },
        cookies=GUEST,
    )
    assert wine_save.status_code == 200, wine_save.text

    assert contract_client.put(f"/api/v1/events/{wine_event_id}/reveal").status_code == 200
    assert contract_client.put(f"/api/v1/events/{wine_event_id}/close").status_code == 200

    wine_detail = contract_client.get(f"/api/v1/events/{wine_event_id}")
    assert wine_detail.status_code == 200, wine_detail.text
    captured["event_detail_wine"] = wine_detail.json()

    listing = contract_client.get("/api/v1/events")
    assert listing.status_code == 200, listing.text
    captured["events_list"] = listing.json()

    # --- Add-bottle-mid-event flow (event-detail.js searchBottlesToAdd +
    # addBottleToEvent). Appended after every capture above so the two extra
    # events cannot change the pre-existing fixtures (events_list is already
    # snapshotted). Guest cookies: the event-detail page is guest-facing.
    add_blind_create = contract_client.post("/api/v1/events", json={
        "name": "Contract Add-Bottle Night",
        "beverage_type": "whiskey",
        "is_blind": True,
        "host_name": "Ben",
        "bottle_ids": [str(bottles[0].id), str(bottles[1].id)],
        "blind_numbers": [1, 2],
    })
    assert add_blind_create.status_code == 200, add_blind_create.text
    add_blind_event_id = add_blind_create.json()["event_id"]

    # The search the page runs before adding — the exact URL event-detail.js
    # builds (q + beverage_type only).
    search = contract_client.get(
        "/api/v1/bottles/search?q=blanton&beverage_type=whiskey",
        cookies=GUEST,
    )
    assert search.status_code == 200, search.text
    captured["event_bottle_search"] = search.json()

    # addBottleToEvent posts {bottle_id: result.bottle_path} — the DB id lives
    # in the search result's bottle_path field.
    add_blind = contract_client.post(
        f"/api/v1/events/{add_blind_event_id}/bottles",
        json={"bottle_id": search.json()["results"][0]["bottle_path"]},
        cookies=GUEST,
    )
    assert add_blind.status_code == 200, add_blind.text
    captured["event_add_bottle_response"] = add_blind.json()

    # Non-blind event: the endpoint echoes the full EventBottle instead of the
    # blind-redacted stub — a genuinely different shape the JS also consumes.
    open_create = contract_client.post("/api/v1/events", json={
        "name": "Contract Open Night",
        "beverage_type": "whiskey",
        "is_blind": False,
        "host_name": "Ben",
        "bottle_ids": [str(bottles[0].id)],
    })
    assert open_create.status_code == 200, open_create.text
    open_event_id = open_create.json()["event_id"]

    add_open = contract_client.post(
        f"/api/v1/events/{open_event_id}/bottles",
        json={"bottle_id": str(bottles[1].id)},
        cookies=GUEST,
    )
    assert add_open.status_code == 200, add_open.text
    captured["event_add_bottle_response_open"] = add_open.json()

    return captured


def test_event_create_response_contract(event_flow):
    assert_contract("event_create_response", event_flow["event_create_response"])


def test_event_join_response_contract(event_flow):
    assert_contract("event_join_response", event_flow["event_join_response"])


def test_manual_tasting_save_response_contract(event_flow):
    assert_contract(
        "manual_tasting_save_response", event_flow["manual_tasting_save_response"]
    )


def test_event_detail_blind_open_contract(event_flow):
    assert_contract("event_detail_blind_open", event_flow["event_detail_blind_open"])


def test_event_detail_contract(event_flow):
    assert_contract("event_detail", event_flow["event_detail"])


def test_event_detail_wine_contract(event_flow):
    assert_contract("event_detail_wine", event_flow["event_detail_wine"])


def test_events_list_contract(event_flow):
    assert_contract("events_list", event_flow["events_list"])


def test_event_bottle_search_contract(event_flow):
    assert_contract("event_bottle_search", event_flow["event_bottle_search"])


def test_event_add_bottle_response_contract(event_flow):
    assert_contract(
        "event_add_bottle_response", event_flow["event_add_bottle_response"]
    )


def test_event_add_bottle_response_open_contract(event_flow):
    assert_contract(
        "event_add_bottle_response_open",
        event_flow["event_add_bottle_response_open"],
    )
