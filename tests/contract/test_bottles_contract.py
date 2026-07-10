"""Contract fixtures for the bottles domain + shared base-page components.

Runs the real bottle lifecycle end-to-end — seed a mixed collection (rich
whiskey, minimal whiskey, two wines), record shared notes, save personal
tastings through the manual-tasting wizard's exact payload, exercise the
upload modal's duplicate-check/save path and the management modal's
field-editor — and snapshots every response shape the frontend consumes:

    bottles_collection            GET  /api/v1/bottles/collection (bottles-page.js)
    bottles_notes_response        PUT  /api/v1/bottles/{id}/notes (bottle-editor-modal.js)
    bottles_tastings_summary      POST /api/v1/bottles/tastings-summary (modal)
    bottles_tastings_list         POST /api/v1/bottles/tastings-list, whiskey (modal)
    bottles_tastings_list_wine    POST /api/v1/bottles/tastings-list, wine (modal)
    bottles_check_duplicates_response POST /api/v1/bottles/check-duplicates (modal)
    bottles_save_duplicate_response   POST /api/v1/bottles/save -> duplicate_found
    bottles_save_response             POST /api/v1/bottles/save -> success
    bottles_management_search     GET  /api/v1/management/bottles/search (modal
                                       manual duplicate override)
    bottles_update_fields_response POST /api/v1/management/bottles/update-fields
                                       (modal saveManagement)
    autocomplete_bottles_producer GET  /api/v1/autocomplete/bottles/producer (modal)
    autocomplete_bottles_variety_error GET /api/v1/autocomplete/bottles/variety —
                                       the modal requests `variety` but the API
                                       rejects it (400); the modal degrades to []
    admin_backup_status           GET  /api/v1/admin/backup-status, stale-ok
    admin_backup_status_unknown   ... status file missing
    admin_backup_status_error     ... backup cron reported an error
                                       (base-page.js backupBanner)

NOT contract-tested (require LM Studio / web search / background image tasks;
their JS fixtures stay hand-written and labeled):
    POST /api/v1/bottles/search-labels          (LLM web image search)
    POST /api/v1/management/bottles/verify      (background LLM enrichment)
    GET  /api/v1/management/tasks/{id}/status   (status of the above)
    label crop/download/upload endpoints        (image ops on real label files)

Backup-status determinism: the route reads /app/data/backup_status.json (an
absolute path written by the prod backup cron). The test points the module's
_BACKUP_STATUS_PATH at files it writes itself — controlling external state,
not faking the endpoint. Ages are computed from utcnow, so last_success is
written with a 30s guard beyond the target minute (45.5 min -> age 45) to
keep the integer stable between capture and compare.

Tasting score design (whiskey /10 = nose/3 + palate/3 + finish/3 + overall/1):
    Eagle Rare (bottle 1): Ben 8.5 (2026-07-01), Sarah 6.5 (2026-07-04)
                           -> count 2, avg 7.5, latest 2026-07-04
    Caymus (bottle 3):     Ben AWS 15.5/20 (2026-07-05)
"""

import json
from datetime import datetime, timedelta

import pytest

from .contract import assert_contract


# The wizard initializes every key and sends the full object (see
# manual-tasting.js tastingData) — whiskey tastings still carry wine_* zeros,
# wine tastings carry whiskey_* zeros, and place/theme/color ride along.
def _wizard_tasting_data(**overrides):
    data = {
        "place": "",
        "theme": "",
        "days_from_crack": None,
        "fill_level": None,
        "color": "",
        "wine_appearance": 0,
        "wine_aroma": 0,
        "wine_taste": 0,
        "wine_aftertaste": 0,
        "wine_overall": 0,
        "whiskey_nose": 0,
        "whiskey_palate": 0,
        "whiskey_finish": 0,
        "whiskey_overall": 0,
        "appearance_notes": [],
        "nose_notes": [],
        "palate_notes": [],
        "finish_notes": [],
        "overall_notes": "",
    }
    data.update(overrides)
    return data


def _wizard_save_payload(taster, date, beverage_type, bottle_id, data):
    # Mirrors manual-tasting.js saveRequest in non-event ("obsidian") mode:
    # the DB bottle id is sent in BOTH fields.
    return {
        "mode": "obsidian",
        "beverage_type": beverage_type,
        "taster_name": taster,
        "tasting_date": date,
        "selected_bottle_id": str(bottle_id),
        "selected_bottle_path": str(bottle_id),
        "tasting_data": data,
    }


# What the upload modal sends to check-duplicates and bottles/save: the
# extraction bottle merged with editableBottle (missing fields become ''),
# then the JS empty-string->null cleanup for year/price/inventory/abv/proof.
NEAR_DUPLICATE_BOTTLE = {
    "type": "whiskey",
    "producer": "Buffalo Trace",
    "name": "Eagle Rare 10",  # fuzzy-matches "Eagle Rare 10 Year"
    "year": 2018,
    "beverage_type": "Bourbon",
    "region": "Kentucky",
    "age_statement": "",
    "proof": None,
    "mash_bill": "",
    "barrel_type": "",
    "batch_number": "",
    "bottle_number": "",
    "bottle_opened_date": "",
    "price": None,
    "inventory": None,
    "purchase_source": "",
    "purchase_link": "",
    "source": "image",
    "confidence": 0.85,
}

NEW_BOTTLE = {
    "type": "whiskey",
    "producer": "Heaven Hill",
    "name": "Elijah Craig Barrel Proof C924",
    "year": 2024,
    "beverage_type": "Bourbon",
    "region": "Kentucky",
    "age_statement": "",
    "proof": 133.2,
    "mash_bill": "",
    "barrel_type": "",
    "batch_number": "C924",
    "bottle_number": "",
    "bottle_opened_date": "",
    "price": None,
    "inventory": None,
    "purchase_source": "",
    "purchase_link": "",
    "source": "image",
    "confidence": 0.9,
}


def _capture_backup_status(contract_client, tmp_dir, captured):
    """Point the route's status-file path at files we control; restore after."""
    from reserve_automation.web.routes import health as health_routes

    original = health_routes._BACKUP_STATUS_PATH
    now = datetime.utcnow()
    try:
        # Missing file -> "unknown"
        health_routes._BACKUP_STATUS_PATH = tmp_dir / "missing_status.json"
        resp = contract_client.get("/api/v1/admin/backup-status")
        assert resp.status_code == 200, resp.text
        captured["admin_backup_status_unknown"] = resp.json()

        # Healthy-but-stale (45.5 min -> age_minutes 45; the 30s guard keeps
        # the integer stable between capture and compare)
        ok_path = tmp_dir / "status_ok.json"
        ok_path.write_text(json.dumps({
            "status": "ok",
            "last_success": (now - timedelta(minutes=45, seconds=30)).isoformat() + "Z",
            "last_attempt": now.isoformat() + "Z",
        }))
        health_routes._BACKUP_STATUS_PATH = ok_path
        resp = contract_client.get("/api/v1/admin/backup-status")
        assert resp.status_code == 200, resp.text
        captured["admin_backup_status"] = resp.json()

        # Cron reported an error (200.5 min -> age 200; adds the `error` key)
        err_path = tmp_dir / "status_error.json"
        err_path.write_text(json.dumps({
            "status": "error",
            "error": "rsync failed: disk full",
            "last_success": (now - timedelta(minutes=200, seconds=30)).isoformat() + "Z",
            "last_attempt": (now - timedelta(minutes=2)).isoformat() + "Z",
        }))
        health_routes._BACKUP_STATUS_PATH = err_path
        resp = contract_client.get("/api/v1/admin/backup-status")
        assert resp.status_code == 200, resp.text
        captured["admin_backup_status_error"] = resp.json()
    finally:
        health_routes._BACKUP_STATUS_PATH = original


@pytest.fixture(scope="module")
def bottles_flow(contract_client, contract_db, tmp_path_factory):
    """Run the full bottles lifecycle once; return every captured response."""
    from reserve_automation.core.models import BottleMetadata
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository

    repo = SQLiteBottleRepository(contract_db)
    # Creation order fixes integer PKs 1..4. GET /collection sorts by
    # (producer, name): Buffalo Trace(1), Caymus(3), Cloudy Bay(4), Willett(2).
    rich_whiskey = repo.create(BottleMetadata(
        producer="Buffalo Trace", name="Eagle Rare 10 Year",
        type="whiskey", source="test", year=2018, beverage_type="Bourbon",
        country="USA", region="Kentucky", age_statement=10, proof=90,
        barrel_type="New Charred Oak", inventory=2, price=49.99,
        purchase_source="Total Wine",
    ))
    repo.create(BottleMetadata(
        # Deliberately minimal: only required fields — the grid's null-guards
        # ((b.region || '') etc.) get exercised by real nulls.
        producer="Willett", name="Pot Still Reserve",
        type="whiskey", source="test",
    ))
    rich_wine = repo.create(BottleMetadata(
        producer="Caymus Vineyards", name="Special Selection Cabernet",
        type="wine", source="test", year=2019, beverage_type="Red",
        country="USA", region="Napa Valley",
        variety=["Cabernet Sauvignon", "Merlot"], vineyard="Rutherford Estate",
        style="Bold", abv=14.8, inventory=1, price=189.0, points="94",
    ))
    repo.create(BottleMetadata(
        # Region-less (country-only) and out of stock — the grid's region
        # fallback and in-stock toggle both depend on this shape.
        producer="Cloudy Bay", name="Sauvignon Blanc Reserve",
        type="wine", source="test", year=2022, beverage_type="White",
        country="New Zealand", variety=["Sauvignon Blanc"], style="Crisp",
        inventory=0,
    ))
    captured = {}

    # --- Shared notes (modal saveNotes: PUT with {notes}) ---
    notes = contract_client.put(
        f"/api/v1/bottles/{rich_whiskey.id}/notes",
        json={"notes": "Great in an Old Fashioned; decant 10 min"},
    )
    assert notes.status_code == 200, notes.text
    captured["bottles_notes_response"] = notes.json()

    # --- Personal tastings through the wizard's exact payload ---
    tastings = [
        ("Ben", "2026-07-01", "whiskey", rich_whiskey.id, _wizard_tasting_data(
            place="Home", theme="Bourbon Night",
            days_from_crack=30, fill_level=90,
            whiskey_nose=2.5, whiskey_palate=3, whiskey_finish=2,
            whiskey_overall=1,
            nose_notes=["caramel", "cherry"], palate_notes=["oak", "brown sugar"],
            finish_notes=["long"], overall_notes="Outstanding pour")),
        ("Sarah", "2026-07-04", "whiskey", rich_whiskey.id, _wizard_tasting_data(
            whiskey_nose=2, whiskey_palate=2, whiskey_finish=2,
            whiskey_overall=0.5,
            nose_notes=["vanilla"], palate_notes=["baking spice"],
            finish_notes=["medium"], overall_notes="")),
        ("Ben", "2026-07-05", "wine", rich_wine.id, _wizard_tasting_data(
            place="Home",
            wine_appearance=2, wine_aroma=5, wine_taste=5,
            wine_aftertaste=2, wine_overall=1.5,
            appearance_notes=["ruby", "opaque"], nose_notes=["cassis", "cocoa"],
            palate_notes=["black cherry"], finish_notes=["long"],
            overall_notes="Special occasion wine")),
    ]
    for taster, date, beverage_type, bottle_id, data in tastings:
        save = contract_client.post(
            "/api/v1/manual-tasting/save",
            json=_wizard_save_payload(taster, date, beverage_type, bottle_id, data),
        )
        assert save.status_code == 200, save.text

    # --- The collection grid (bottles-page.js loadBottles) ---
    collection = contract_client.get("/api/v1/bottles/collection")
    assert collection.status_code == 200, collection.text
    captured["bottles_collection"] = collection.json()

    # The modal is opened WITH a grid bottle and posts it back verbatim —
    # so the tastings requests must carry the collection entry, not a
    # hand-built dict.
    by_id = {b["id"]: b for b in collection.json()["bottles"]}
    whiskey_from_api = by_id[str(rich_whiskey.id)]
    wine_from_api = by_id[str(rich_wine.id)]

    summary = contract_client.post(
        "/api/v1/bottles/tastings-summary", json={"bottle": whiskey_from_api},
    )
    assert summary.status_code == 200, summary.text
    captured["bottles_tastings_summary"] = summary.json()

    tlist = contract_client.post(
        "/api/v1/bottles/tastings-list", json={"bottle": whiskey_from_api},
    )
    assert tlist.status_code == 200, tlist.text
    captured["bottles_tastings_list"] = tlist.json()

    tlist_wine = contract_client.post(
        "/api/v1/bottles/tastings-list", json={"bottle": wine_from_api},
    )
    assert tlist_wine.status_code == 200, tlist_wine.text
    captured["bottles_tastings_list_wine"] = tlist_wine.json()

    # --- Upload modal: duplicate check + save (near-duplicate of bottle 1) ---
    check = contract_client.post(
        "/api/v1/bottles/check-duplicates", json=NEAR_DUPLICATE_BOTTLE,
    )
    assert check.status_code == 200, check.text
    assert check.json()["count"] >= 1  # the flow depends on a real fuzzy hit
    captured["bottles_check_duplicates_response"] = check.json()

    # saveUpload wrapper exactly as the modal builds it (it also sends a
    # temp_label_path key the server schema doesn't define — ignored).
    dup_save = contract_client.post("/api/v1/bottles/save", json={
        "bottle": {**NEAR_DUPLICATE_BOTTLE, "notes": None},
        "upload_id": "contract-upload-1",
        "temp_label_path": None,
        "force_save": False,
        "replace_bottle_id": None,
    })
    assert dup_save.status_code == 200, dup_save.text
    assert dup_save.json()["status"] == "duplicate_found"
    captured["bottles_save_duplicate_response"] = dup_save.json()

    new_save = contract_client.post("/api/v1/bottles/save", json={
        "bottle": {**NEW_BOTTLE, "notes": "Hazmat — small pours"},
        "upload_id": "contract-upload-1",
        "temp_label_path": None,
        "force_save": False,
        "replace_bottle_id": None,
    })
    assert new_save.status_code == 200, new_save.text
    assert new_save.json()["status"] == "success"
    captured["bottles_save_response"] = new_save.json()

    # --- Manual duplicate override search (modal manualMatchSearch) ---
    # "reserve" hits one wine and one whiskey — the modal sorts same-type first.
    search = contract_client.get("/api/v1/management/bottles/search?q=reserve")
    assert search.status_code == 200, search.text
    captured["bottles_management_search"] = search.json()

    # --- Autocomplete (modal loadAutocomplete) ---
    ac = contract_client.get("/api/v1/autocomplete/bottles/producer")
    assert ac.status_code == 200, ac.text
    captured["autocomplete_bottles_producer"] = ac.json()

    # The modal also requests `variety`, which the API rejects (stored as a
    # JSON list — see autocomplete.py); the modal's r.ok guard turns this
    # into []. Snapshot the 400 body so the mismatch stays visible.
    ac_variety = contract_client.get("/api/v1/autocomplete/bottles/variety")
    assert ac_variety.status_code == 400, ac_variety.text
    captured["autocomplete_bottles_variety_error"] = ac_variety.json()

    # --- Backup banner (base-page.js) ---
    _capture_backup_status(
        contract_client, tmp_path_factory.mktemp("backup_status"), captured,
    )

    # --- Management modal field save (saveManagement). LAST: it mutates
    # bottle 1, and every earlier fixture snapshots pre-edit state. ---
    update = contract_client.post(
        "/api/v1/management/bottles/update-fields",
        json={
            "bottle": whiskey_from_api,
            # The modal sends the FULL editableBottle: unchanged fields ride
            # along, missing ones as '' (the template's input defaults).
            "updates": {
                "producer": "Buffalo Trace",
                "name": "Eagle Rare 10 Year",
                "year": 2018,
                "beverage_type": "Bourbon",
                "price": 54.99,
                "inventory": 2,
                "purchase_source": "Total Wine",
                "purchase_link": "",
                "region": "Kentucky",
                "age_statement": 10,
                "proof": 90,
                "mash_bill": "",
                "barrel_type": "Toasted Oak",
                "batch_number": "",
                "bottle_number": "",
                "bottle_opened_date": "",
            },
        },
    )
    assert update.status_code == 200, update.text
    captured["bottles_update_fields_response"] = update.json()

    return captured


def test_bottles_collection_contract(bottles_flow):
    assert_contract("bottles_collection", bottles_flow["bottles_collection"])


def test_bottles_notes_response_contract(bottles_flow):
    assert_contract("bottles_notes_response", bottles_flow["bottles_notes_response"])


def test_bottles_tastings_summary_contract(bottles_flow):
    assert_contract(
        "bottles_tastings_summary", bottles_flow["bottles_tastings_summary"]
    )


def test_bottles_tastings_list_contract(bottles_flow):
    assert_contract("bottles_tastings_list", bottles_flow["bottles_tastings_list"])


def test_bottles_tastings_list_wine_contract(bottles_flow):
    assert_contract(
        "bottles_tastings_list_wine", bottles_flow["bottles_tastings_list_wine"]
    )


def test_bottles_check_duplicates_response_contract(bottles_flow):
    assert_contract(
        "bottles_check_duplicates_response",
        bottles_flow["bottles_check_duplicates_response"],
    )


def test_bottles_save_duplicate_response_contract(bottles_flow):
    assert_contract(
        "bottles_save_duplicate_response",
        bottles_flow["bottles_save_duplicate_response"],
    )


def test_bottles_save_response_contract(bottles_flow):
    assert_contract("bottles_save_response", bottles_flow["bottles_save_response"])


def test_bottles_management_search_contract(bottles_flow):
    assert_contract(
        "bottles_management_search", bottles_flow["bottles_management_search"]
    )


def test_bottles_update_fields_response_contract(bottles_flow):
    assert_contract(
        "bottles_update_fields_response",
        bottles_flow["bottles_update_fields_response"],
    )


def test_autocomplete_bottles_producer_contract(bottles_flow):
    assert_contract(
        "autocomplete_bottles_producer",
        bottles_flow["autocomplete_bottles_producer"],
    )


def test_autocomplete_bottles_variety_error_contract(bottles_flow):
    assert_contract(
        "autocomplete_bottles_variety_error",
        bottles_flow["autocomplete_bottles_variety_error"],
    )


def test_admin_backup_status_contract(bottles_flow):
    assert_contract("admin_backup_status", bottles_flow["admin_backup_status"])


def test_admin_backup_status_unknown_contract(bottles_flow):
    assert_contract(
        "admin_backup_status_unknown", bottles_flow["admin_backup_status_unknown"]
    )


def test_admin_backup_status_error_contract(bottles_flow):
    assert_contract(
        "admin_backup_status_error", bottles_flow["admin_backup_status_error"]
    )
