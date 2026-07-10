"""Contract fixtures for the cocktail system.

Runs the real cocktail lifecycle through the API — three recipes created with
the exact payload cocktails-page.js saveCocktail sends (one a variation with a
parent_cocktail), two tastings saved through the "Rate This" wizard's exact
payload (cocktail-detail.js saveTasting), then re-dated through the
edit-tasting modal's exact PATCH payload (saveEditTasting) — and snapshots
every response shape the frontend consumes:

    cocktails_list      GET /api/v1/cocktails            (cocktails-page.js,
                        cocktail-detail.js sibling names)
    cocktails_search    GET /api/v1/cocktails?q=Old Fashioned
                        (cocktails-page.js loadCocktails with searchQuery)
    cocktail_detail     GET /api/v1/cocktails/{id} for the variation —
                        carries parent_cocktail (cocktail-detail.js; omitting
                        this field is the July 2026 edit-wipe bug)
    cocktail_tastings   GET /api/v1/cocktails/{id}/tastings
                        (cocktail-detail.js loadTastings/avgScore)

Dates: the create-tasting endpoint stamps date.today() server-side (the wizard
sends no date), which would make snapshots drift daily. The flow therefore
PATCHes each tasting through the edit-tasting modal's exact payload with a
fixed tasting_date — a real user flow, and it pins the fixture.

Deliberately NOT captured:
- POST /api/v1/cocktails/search-recipe is LLM-backed (LM Studio); its shape
  cannot be captured without the model. The JS suite keeps a labelled
  hand-written fixture for it.
- Create/update/delete and tasting-save success bodies: the frontend never
  reads them (it only branches on response.ok and reloads).

Recipe ingredient names (Bourbon, Brandy, Whiskey, Angostura Bitters) match
the tree seeded by test_ingredients_contract.py, so the cocktails_ and
ingredients_ fixture families describe one coherent world for the JS suites.

Score design: Ben 9 + Sarah 8 on the Wisconsin Old Fashioned -> avg 8.5 in
cocktails_list/cocktail_detail; the other two cocktails stay unscored (null).
"""

import pytest

from .contract import assert_contract


def _recipe_row(ingredient, amount, unit, notes="", optional=False):
    """One ingredient row exactly as the create/edit recipe forms send it."""
    return {
        "ingredient": ingredient,
        "amount": amount,
        "unit": unit,
        "notes": notes,
        "optional": optional,
    }


# The exact bodies cocktails-page.js saveCocktail POSTs ('' already collapsed
# to null, blank rows already filtered). Creation order == integer PK order.
COCKTAIL_SEED = [
    {  # id 1
        "name": "Old Fashioned",
        "description": "The original whiskey cocktail",
        "parent_cocktail": None,
        "method": "stirred",
        "style": "classic",
        "glassware": "rocks",
        "garnish": "orange peel",
        "ingredients": [
            _recipe_row("Bourbon", 2, "oz"),
            _recipe_row("Angostura Bitters", 2, "dash"),
            _recipe_row("Sugar", 1, "cube", notes="demerara"),
        ],
        "instructions": [
            "Muddle the sugar with the bitters",
            "Add bourbon and ice, stir until chilled",
            "Garnish with an expressed orange peel",
        ],
    },
    {  # id 2 — the variation: parent_cocktail set, four ingredients, one optional
        "name": "Wisconsin Old Fashioned",
        "description": "Brandy old fashioned sweet, the supper club standard",
        "parent_cocktail": "Old Fashioned",
        "method": "built",
        "style": "classic",
        "glassware": "rocks",
        "garnish": "orange slice and brandied cherry",
        "ingredients": [
            _recipe_row("Brandy", 2, "oz"),
            _recipe_row("Angostura Bitters", 3, "dash"),
            _recipe_row("Sugar", 1, "cube", notes="muddled with the bitters"),
            _recipe_row("Lemon-Lime Soda", 2, "oz", notes="to top", optional=True),
        ],
        "instructions": [
            "Muddle sugar, bitters and orange in the glass",
            "Add brandy and ice",
            "Top with lemon-lime soda",
        ],
    },
    {  # id 3
        "name": "Manhattan",
        "description": None,
        "parent_cocktail": None,
        "method": "stirred",
        "style": "classic",
        "glassware": "coupe",
        "garnish": "brandied cherry",
        "ingredients": [
            _recipe_row("Whiskey", 2, "oz"),
            _recipe_row("Sweet Vermouth", 1, "oz"),
            _recipe_row("Angostura Bitters", 2, "dash"),
        ],
        "instructions": ["Stir with ice", "Strain into a chilled coupe"],
    },
]


def _wizard_tasting_payload(taster_name, score, notes, bartender, bottles_used):
    """The exact body cocktail-detail.js saveTasting POSTs (no tasting_date —
    the server stamps today; empty bottle rows already dropped)."""
    return {
        "taster_name": taster_name,
        "score": score,
        "notes": notes,
        "bartender": bartender,
        "bottles_used": bottles_used,
    }


def _edit_tasting_payload(taster_name, tasting_date, score, notes, bartender,
                          bottles_used):
    """The exact body cocktail-detail.js saveEditTasting PATCHes."""
    return {
        "taster_name": taster_name,
        "tasting_date": tasting_date,
        "score": score,
        "notes": notes,
        "bartender": bartender,
        "bottles_used": bottles_used,
    }


@pytest.fixture(scope="module")
def cocktail_flow(contract_client, contract_db):
    """Run the full cocktail lifecycle once; return every captured response."""
    ids = {}
    for payload in COCKTAIL_SEED:
        response = contract_client.post("/api/v1/cocktails", json=payload)
        assert response.status_code == 200, response.text
        ids[payload["name"]] = response.json()["id"]
    wisconsin_id = ids["Wisconsin Old Fashioned"]

    ben_bottles = [
        {"recipe_ingredient": "Brandy", "actual_product": "Korbel Brandy"},
        {"recipe_ingredient": "Angostura Bitters",
         "actual_product": "Angostura Bitters"},
    ]
    tastings = [
        # (wizard POST payload, fixed date PATCHed through the edit modal)
        (_wizard_tasting_payload(
            "Ben", 9, "Nailed the supper club vibe", "Sarah", ben_bottles,
        ), "2026-07-07", ben_bottles),
        # Untouched notes/bartender fields go up as '' (the wizard's defaults)
        (_wizard_tasting_payload("Sarah", 8, "", "", []), "2026-07-06", []),
    ]
    for post_payload, fixed_date, bottles in tastings:
        save = contract_client.post(
            f"/api/v1/cocktails/{wisconsin_id}/tastings", json=post_payload,
        )
        assert save.status_code == 200, save.text
        tasting_id = save.json()["id"]

        # The wizard cannot set a date (server stamps today) — re-date through
        # the edit-tasting modal's exact flow so the snapshot is deterministic.
        patch = contract_client.patch(
            f"/api/v1/cocktails/{wisconsin_id}/tastings/{tasting_id}",
            json=_edit_tasting_payload(
                post_payload["taster_name"], fixed_date, post_payload["score"],
                post_payload["notes"], post_payload["bartender"], bottles,
            ),
        )
        assert patch.status_code == 200, patch.text

    captured = {}

    listing = contract_client.get("/api/v1/cocktails")
    assert listing.status_code == 200, listing.text
    captured["cocktails_list"] = listing.json()

    search = contract_client.get(
        "/api/v1/cocktails", params={"q": "Old Fashioned"},
    )
    assert search.status_code == 200, search.text
    captured["cocktails_search"] = search.json()

    detail = contract_client.get(f"/api/v1/cocktails/{wisconsin_id}")
    assert detail.status_code == 200, detail.text
    captured["cocktail_detail"] = detail.json()

    tastings_list = contract_client.get(
        f"/api/v1/cocktails/{wisconsin_id}/tastings",
    )
    assert tastings_list.status_code == 200, tastings_list.text
    captured["cocktail_tastings"] = tastings_list.json()

    return captured


def test_cocktails_list_contract(cocktail_flow):
    assert_contract("cocktails_list", cocktail_flow["cocktails_list"])


def test_cocktails_search_contract(cocktail_flow):
    assert_contract("cocktails_search", cocktail_flow["cocktails_search"])


def test_cocktail_detail_contract(cocktail_flow):
    assert_contract("cocktail_detail", cocktail_flow["cocktail_detail"])


def test_cocktail_tastings_contract(cocktail_flow):
    assert_contract("cocktail_tastings", cocktail_flow["cocktail_tastings"])
