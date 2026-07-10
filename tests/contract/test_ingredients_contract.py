"""Contract fixtures for the ingredient tree system.

Builds the ingredient tree the way the frontend does — every node POSTed
through /api/v1/ingredients with the exact payload ingredients-page.js
saveIngredient sends ('' collapsed to null, every field present) — then
snapshots every response shape the frontend consumes:

    ingredient_create_response  POST /api/v1/ingredients
                                (ingredients-page.js saveIngredient; ALSO read
                                by cocktails-page.js saveNewIngredient and
                                cocktail-detail.js createAndSelectIngredient)
    ingredients_tree            GET /api/v1/ingredients
                                (ingredients-page.js loadTree — nested dicts)
    ingredients_flat            GET /api/v1/ingredients?flat=true
                                (cocktails-page.js / cocktail-detail.js
                                loadIngredientNames + searchBottles — NOTE:
                                flat dicts carry ancestors but NO children key)
    ingredients_search          GET /api/v1/ingredients/search?q=bo
                                (ingredients-page.js doSearch, cocktail-detail.js
                                searchBottles — matches are FLAT: children is
                                always [] because the repo returns bare rows)
    ingredient_detail           GET /api/v1/ingredients/{id} for Bourbon
                                (ingredients-page.js viewIngredientByName —
                                ancestors + direct children populated)
    ingredient_descendants      GET /api/v1/ingredients/{id}/descendants for
                                Whiskey (cocktail-detail.js searchBottles smart
                                default — flat dicts, ancestors NOT computed)

Tree design (3 levels, so flat/descendants/search differ meaningfully):

    Bitters -> Angostura Bitters (product)
    Brandy  -> Korbel Brandy (product)
    Whiskey -> Bourbon -> Buffalo Trace Bourbon (product)
                       -> Eagle Rare 10 Year (product)

The search fixture uses q="bo" on purpose: it matches the Bourbon category
AND the Buffalo Trace Bourbon product, giving the JS suites a real
category+product result set (product-first sorting) with an exact-name match
("Bourbon") that lines up with ingredient_detail.

Cocktail recipes in test_cocktails_contract.py reference these same names
(Bourbon, Brandy, Whiskey, Angostura Bitters) so the two fixture families
describe one coherent world for the JS suites.
"""

import pytest

from .contract import assert_contract


def _form_payload(name, parent=None, cost=None, volume_ml=None, abv=None, notes=None):
    """The exact body ingredients-page.js saveIngredient POSTs: every field
    present, empty strings already collapsed to null."""
    return {
        "name": name,
        "parent": parent,
        "cost": cost,
        "volume_ml": volume_ml,
        "abv": abv,
        "notes": notes,
    }


# Creation order == integer PK order (DB is wiped at module setup).
TREE_SEED = [
    _form_payload("Whiskey"),                                           # id 1
    _form_payload("Bourbon", parent="Whiskey"),                         # id 2
    _form_payload("Buffalo Trace Bourbon", parent="Bourbon",            # id 3
                  cost=29.99, volume_ml=750, abv=45.0, notes="Shelf staple"),
    _form_payload("Eagle Rare 10 Year", parent="Bourbon",               # id 4
                  cost=39.99, volume_ml=750, abv=45.0),
    _form_payload("Brandy"),                                            # id 5
    _form_payload("Korbel Brandy", parent="Brandy",                     # id 6
                  cost=15.99, volume_ml=750, abv=40.0),
    _form_payload("Bitters"),                                           # id 7
    _form_payload("Angostura Bitters", parent="Bitters",                # id 8
                  cost=11.49, volume_ml=118, abv=44.7,
                  notes="The classic aromatic bitters"),
]


def seed_ingredient_tree(client) -> dict:
    """POST the whole tree through the API; return the last create response
    (a product with every field set — the richest create shape)."""
    last = None
    for payload in TREE_SEED:
        response = client.post("/api/v1/ingredients", json=payload)
        assert response.status_code == 200, response.text
        last = response.json()
    return last


@pytest.fixture(scope="module")
def ingredient_flow(contract_client, contract_db):
    """Build the tree through the API once; return every captured response."""
    captured = {}
    captured["ingredient_create_response"] = seed_ingredient_tree(contract_client)

    tree = contract_client.get("/api/v1/ingredients")
    assert tree.status_code == 200, tree.text
    captured["ingredients_tree"] = tree.json()

    flat = contract_client.get("/api/v1/ingredients", params={"flat": "true"})
    assert flat.status_code == 200, flat.text
    captured["ingredients_flat"] = flat.json()

    search = contract_client.get("/api/v1/ingredients/search", params={"q": "bo"})
    assert search.status_code == 200, search.text
    captured["ingredients_search"] = search.json()

    # Resolve ids by name from the flat response instead of hardcoding.
    by_name = {i["name"]: i["id"] for i in captured["ingredients_flat"]}

    detail = contract_client.get(f"/api/v1/ingredients/{by_name['Bourbon']}")
    assert detail.status_code == 200, detail.text
    captured["ingredient_detail"] = detail.json()

    descendants = contract_client.get(
        f"/api/v1/ingredients/{by_name['Whiskey']}/descendants"
    )
    assert descendants.status_code == 200, descendants.text
    captured["ingredient_descendants"] = descendants.json()

    return captured


def test_ingredient_create_response_contract(ingredient_flow):
    assert_contract(
        "ingredient_create_response", ingredient_flow["ingredient_create_response"]
    )


def test_ingredients_tree_contract(ingredient_flow):
    assert_contract("ingredients_tree", ingredient_flow["ingredients_tree"])


def test_ingredients_flat_contract(ingredient_flow):
    assert_contract("ingredients_flat", ingredient_flow["ingredients_flat"])


def test_ingredients_search_contract(ingredient_flow):
    assert_contract("ingredients_search", ingredient_flow["ingredients_search"])


def test_ingredient_detail_contract(ingredient_flow):
    assert_contract("ingredient_detail", ingredient_flow["ingredient_detail"])


def test_ingredient_descendants_contract(ingredient_flow):
    assert_contract("ingredient_descendants", ingredient_flow["ingredient_descendants"])
