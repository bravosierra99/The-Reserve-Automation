"""Contract fixtures for the management page domain.

Runs the real management flows end-to-end and snapshots every response shape
the management frontends consume (management-app.js, tasting-review.js,
event-create.js):

    management_batch_verify_response  POST /api/v1/management/bottles/batch-verify
                                      (management-app.js startBatchVerification).
                                      Captured against an EMPTY bottle table:
                                      with bottles present the background tasks
                                      call the LLM (ExtractionService), so only
                                      the top-level batch shape is capturable.
    management_batch_status           GET /api/v1/management/batch/{id}/status
                                      (management-app.js pollBatchStatus). Same
                                      limit: results[] entries require the LLM,
                                      so the fixture carries the completed-empty
                                      batch; per-result shapes stay hand-written
                                      in the JS suite.
    management_bottle_search          GET /api/v1/management/bottles/search?q=
                                      (event-create.js searchBottlesForEvent)
    management_tasting_update_response PATCH /api/v1/management/tastings/{kind}/{id}
                                      (tasting-review.js trSaveEdit /
                                      trCocktailSaveEdit / trToggleHidden)
    management_tastings               GET /api/v1/management/tastings
                                      (tasting-review.js loadTastings) — one
                                      whiskey, one wine and one cocktail tasting,
                                      each saved through its real frontend save
                                      endpoint with the exact wizard payloads
    management_cocktail_detail        GET /api/v1/cocktails/{id}
                                      (tasting-review.js trOpenCocktailModal)
    management_field_values           GET /api/v1/management/field-values
                                      (management-app.js loadCleanupValues)
    management_bulk_rename_response   POST /api/v1/management/bulk-rename
                                      (management-app.js dcApplyRename)
    management_bulk_save_response     POST /api/v1/ingredients/bulk-save
                                      (management-app.js doBulkSave)
    management_event_reveal_response  PUT /api/v1/events/{id}/reveal
                                      (management-app.js revealEventBottles)
    management_event_close_response   PUT /api/v1/events/{id}/close
                                      (management-app.js closeEventFromManagement)
    management_tasting_delete_response DELETE /api/v1/management/tastings/{kind}/{id}
                                      (tasting-review.js trDeleteTasting)

NOT contract-testable here:
    POST /api/v1/ingredients/bulk-search — performs a live web search and an
    LLM completion (routes/ingredients.py); its response cannot be captured
    deterministically. The JS suite keeps a labelled hand-written fixture.

The cocktail tasting POST (/api/v1/cocktails/{id}/tastings) stamps
date.today() server-side (the frontend sends no date), so after saving it the
flow PATCHes a fixed tasting_date through the management endpoint — exactly
what tasting-review.js trCocktailSaveEdit does — to keep the snapshot stable.
"""

import pytest

from .contract import assert_contract


def _wizard_tasting_data(**overrides):
    """The manual-tasting wizard's full tastingData object (manual-tasting.js):
    every key is initialized and the whole object is sent, so whiskey tastings
    still carry wine_* zeros and vice versa."""
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


def _wizard_save_payload(taster, date, bottle_id, beverage_type, data):
    # Mirrors manual-tasting.js saveRequest in standalone (non-event) mode:
    # mode "obsidian", DB bottle id sent in BOTH bottle fields.
    return {
        "mode": "obsidian",
        "beverage_type": beverage_type,
        "taster_name": taster,
        "tasting_date": date,
        "selected_bottle_id": str(bottle_id),
        "selected_bottle_path": str(bottle_id),
        "tasting_data": data,
    }


@pytest.fixture(scope="module")
def management_flow(contract_client, contract_db):
    """Run the management flows once; return every captured response."""
    from reserve_automation.core.models import BottleMetadata
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository

    client = contract_client
    captured = {}

    # --- Batch verification, on the still-empty bottle table (see module
    # docstring): zero bottles means zero LLM background tasks, and the batch
    # completes immediately with empty results.
    batch = client.post("/api/v1/management/bottles/batch-verify")
    assert batch.status_code == 200, batch.text
    captured["management_batch_verify_response"] = batch.json()

    batch_status = client.get(
        f"/api/v1/management/batch/{batch.json()['batch_id']}/status"
    )
    assert batch_status.status_code == 200, batch_status.text
    captured["management_batch_status"] = batch_status.json()

    # --- Seed bottles via the repository (fixed metadata).
    repo = SQLiteBottleRepository(contract_db)
    weller12 = repo.create(BottleMetadata(
        producer="Buffalo Trace", name="Weller 12 Year",
        type="whiskey", source="test", beverage_type="Bourbon",
        country="USA", region="Kentucky", proof=90, age_statement=12,
        mash_bill="Wheated", barrel_type="New American Oak",
        price=39.99, purchase_source="Liquor Barn", inventory=1,
    ))
    weller_sr = repo.create(BottleMetadata(
        producer="Buffalo Trace", name="Weller Special Reserve",
        type="whiskey", source="test", beverage_type="Bourbon",
        country="USA", region="Kentucky", proof=90, inventory=1,
    ))
    caymus = repo.create(BottleMetadata(
        producer="Caymus Vineyards", name="Cabernet Sauvignon",
        type="wine", source="test", beverage_type="Red Wine", year=2021,
        variety=["Cabernet Sauvignon"], country="USA", region="Napa Valley",
        style="Bold", vineyard="Caymus Estate", abv=14.5,
        price=89.99, purchase_source="Total Wine", inventory=1,
    ))

    # --- Bottle search (event-create picker).
    search = client.get("/api/v1/management/bottles/search", params={"q": "Weller"})
    assert search.status_code == 200, search.text
    assert search.json()["count"] == 2, search.text
    captured["management_bottle_search"] = search.json()

    # --- Save a whiskey and a wine tasting through the manual-tasting wizard.
    whiskey_save = client.post("/api/v1/manual-tasting/save", json=_wizard_save_payload(
        "Ben", "2026-07-01", weller12.id, "whiskey",
        _wizard_tasting_data(
            whiskey_nose=2.5, whiskey_palate=3, whiskey_finish=2, whiskey_overall=1,
            days_from_crack=12, fill_level=80,
            nose_notes=["caramel", "oak"], palate_notes=["cherry"],
            finish_notes=["long"], overall_notes="Great pour",
        ),
    ))
    assert whiskey_save.status_code == 200, whiskey_save.text

    wine_save = client.post("/api/v1/manual-tasting/save", json=_wizard_save_payload(
        "Sarah", "2026-07-03", caymus.id, "wine",
        _wizard_tasting_data(
            wine_appearance=3, wine_aroma=5, wine_taste=5,
            wine_aftertaste=2, wine_overall=2,
            appearance_notes=["ruby"], nose_notes=["blackberry", "cassis"],
            palate_notes=["tannic"], finish_notes=["long"],
            overall_notes="Lovely",
        ),
    ))
    assert wine_save.status_code == 200, wine_save.text

    # --- Cocktail: create a recipe (cocktails-page.js saveCocktail payload),
    # save a tasting for it (cocktail-detail.js saveTasting payload).
    recipe = client.post("/api/v1/cocktails", json={
        "name": "Contract Old Fashioned",
        "description": None,
        "parent_cocktail": None,
        "method": "Stirred",
        "style": "Spirit-forward",
        "glassware": "Rocks",
        "garnish": "Orange peel",
        "ingredients": [
            {"ingredient": "Bourbon", "amount": 2, "unit": "oz",
             "notes": "", "optional": False},
            {"ingredient": "Sweet Vermouth", "amount": 1, "unit": "oz",
             "notes": "", "optional": False},
        ],
        "instructions": ["Stir with ice", "Strain over a large cube"],
    })
    assert recipe.status_code == 200, recipe.text
    cocktail_id = recipe.json()["id"]

    cocktail_tasting = client.post(f"/api/v1/cocktails/{cocktail_id}/tastings", json={
        "taster_name": "Ben",
        "score": 8,
        "notes": "Well balanced",
        "bartender": "Ben",
        "bottles_used": [
            {"recipe_ingredient": "Bourbon",
             "actual_product": "Weller Special Reserve"},
        ],
    })
    assert cocktail_tasting.status_code == 200, cocktail_tasting.text
    cocktail_tasting_id = cocktail_tasting.json()["id"]

    # The POST stamped today's date; pin it through the management PATCH —
    # the exact request trCocktailSaveEdit sends (including the empty
    # actual_product row the modal keeps for unfilled ingredients).
    update = client.patch(
        f"/api/v1/management/tastings/cocktail/{cocktail_tasting_id}",
        json={
            "taster_name": "Ben",
            "tasting_date": "2026-07-05",
            "score": 8,
            "notes": "Well balanced",
            "bartender": "Ben",
            "bottles_used": [
                {"recipe_ingredient": "Bourbon",
                 "actual_product": "Weller Special Reserve"},
                {"recipe_ingredient": "Sweet Vermouth", "actual_product": ""},
            ],
        },
    )
    assert update.status_code == 200, update.text
    captured["management_tasting_update_response"] = update.json()

    # --- THE tasting-review fixture.
    tastings = client.get("/api/v1/management/tastings")
    assert tastings.status_code == 200, tastings.text
    captured["management_tastings"] = tastings.json()

    # --- Recipe as the cocktail edit modal fetches it.
    detail = client.get(f"/api/v1/cocktails/{cocktail_id}")
    assert detail.status_code == 200, detail.text
    captured["management_cocktail_detail"] = detail.json()

    # --- Data cleanup: field values then a bulk rename (loadCleanupValues
    # defaults: scope=tastings, field=taster_name).
    field_values = client.get(
        "/api/v1/management/field-values",
        params={"scope": "tastings", "field": "taster_name"},
    )
    assert field_values.status_code == 200, field_values.text
    captured["management_field_values"] = field_values.json()

    rename = client.post("/api/v1/management/bulk-rename", json={
        "scope": "tastings", "field": "taster_name",
        "old_value": "Sarah", "new_value": "Sarah B",
    })
    assert rename.status_code == 200, rename.text
    captured["management_bulk_rename_response"] = rename.json()

    # --- Bulk ingredient save (doBulkSave posts parent + the FULL results
    # list, selected and unselected alike — the unselected row comes back
    # skipped).
    bulk_save = client.post("/api/v1/ingredients/bulk-save", json={
        "parent": None,
        "ingredients": [
            {"name": "Angostura Aromatic Bitters", "cost": 12.99,
             "volume_ml": 200, "abv": 44.7,
             "notes": "Classic aromatic bitters", "selected": True},
            {"name": "Peychaud's Bitters", "cost": 11.49,
             "volume_ml": 148, "abv": 35.0,
             "notes": "New Orleans style bitters", "selected": True},
            {"name": "Regans' Orange Bitters", "cost": 9.99,
             "volume_ml": 148, "abv": 45.0,
             "notes": "Orange bitters", "selected": False},
        ],
    })
    assert bulk_save.status_code == 200, bulk_save.text
    captured["management_bulk_save_response"] = bulk_save.json()

    # --- Manage-events actions on an event of our own (event-create.js
    # createEvent payload; blind numbers fixed instead of shuffled).
    event = client.post("/api/v1/events", json={
        "name": "Contract Management Night",
        "beverage_type": "whiskey",
        "is_blind": True,
        "host_name": "Ben",
        "bottle_ids": [str(weller12.id), str(weller_sr.id)],
        "blind_numbers": [1, 2],
    })
    assert event.status_code == 200, event.text
    event_id = event.json()["event_id"]

    reveal = client.put(f"/api/v1/events/{event_id}/reveal")
    assert reveal.status_code == 200, reveal.text
    captured["management_event_reveal_response"] = reveal.json()

    close = client.put(f"/api/v1/events/{event_id}/close")
    assert close.status_code == 200, close.text
    captured["management_event_close_response"] = close.json()

    # --- Delete a tasting (last: it mutates the tasting list).
    wine_row = next(
        t for t in captured["management_tastings"]["tastings"] if t["type"] == "wine"
    )
    delete = client.delete(f"/api/v1/management/tastings/bottle/{wine_row['id']}")
    assert delete.status_code == 200, delete.text
    captured["management_tasting_delete_response"] = delete.json()

    return captured


def test_management_batch_verify_response_contract(management_flow):
    assert_contract(
        "management_batch_verify_response",
        management_flow["management_batch_verify_response"],
    )


def test_management_batch_status_contract(management_flow):
    assert_contract(
        "management_batch_status", management_flow["management_batch_status"]
    )


def test_management_bottle_search_contract(management_flow):
    assert_contract(
        "management_bottle_search", management_flow["management_bottle_search"]
    )


def test_management_tasting_update_response_contract(management_flow):
    assert_contract(
        "management_tasting_update_response",
        management_flow["management_tasting_update_response"],
    )


def test_management_tastings_contract(management_flow):
    assert_contract("management_tastings", management_flow["management_tastings"])


def test_management_cocktail_detail_contract(management_flow):
    assert_contract(
        "management_cocktail_detail", management_flow["management_cocktail_detail"]
    )


def test_management_field_values_contract(management_flow):
    assert_contract(
        "management_field_values", management_flow["management_field_values"]
    )


def test_management_bulk_rename_response_contract(management_flow):
    assert_contract(
        "management_bulk_rename_response",
        management_flow["management_bulk_rename_response"],
    )


def test_management_bulk_save_response_contract(management_flow):
    assert_contract(
        "management_bulk_save_response",
        management_flow["management_bulk_save_response"],
    )


def test_management_event_reveal_response_contract(management_flow):
    assert_contract(
        "management_event_reveal_response",
        management_flow["management_event_reveal_response"],
    )


def test_management_event_close_response_contract(management_flow):
    assert_contract(
        "management_event_close_response",
        management_flow["management_event_close_response"],
    )


def test_management_tasting_delete_response_contract(management_flow):
    assert_contract(
        "management_tasting_delete_response",
        management_flow["management_tasting_delete_response"],
    )
