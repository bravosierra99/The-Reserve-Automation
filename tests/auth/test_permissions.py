"""Test per-route permission enforcement across roles.

Tests that key endpoints return 200 for allowed roles and 403 for denied roles.
Uses dev mode with cookie-based role switching.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def perm_vault(tmp_path_factory):
    """Create a minimal test vault for permission tests."""
    vault_path = tmp_path_factory.mktemp("perm-vault")

    # Create minimal vault structure
    for subdir in ["1_Wines", "1_Whiskeys", "2_Ingredients", "3_Cocktails"]:
        (vault_path / subdir).mkdir(exist_ok=True)

    # Create a test ingredient
    ing_dir = vault_path / "2_Ingredients" / "Vodka"
    ing_dir.mkdir(parents=True)
    (ing_dir / "Vodka.md").write_text(
        "---\nfileClass: Ingredient\nIngredientName: Vodka\nParent:\n---\n"
    )

    # Create a test cocktail
    cocktail_dir = vault_path / "3_Cocktails" / "Moscow Mule"
    cocktail_dir.mkdir(parents=True)
    (cocktail_dir / "Moscow Mule.md").write_text(
        "---\nfileClass: Cocktail\nCocktailName: Moscow Mule\nCategory: Classic\n"
        "Glass: Copper Mug\nMethod: Build\nIngredients:\n  - ingredient: Vodka\n"
        "    amount: '2 oz'\nGarnish: []\nSteps:\n  - Pour vodka\nNotes:\nRating:\n---\n"
    )

    return vault_path


@pytest.fixture(scope="module")
def perm_client(perm_vault):
    """Create a test client with auth enabled for permission testing."""
    os.environ["RESERVE_VAULT_PATH"] = str(perm_vault)
    os.environ["WEB_SECRET_KEY"] = "test_secret_key_for_testing_only_not_secure_32_chars_min"

    from reserve_automation.web.app import app
    from reserve_automation.web.auth.config import load_auth_config
    from reserve_automation.web.config import load_web_config

    core_config, web_config = load_web_config()

    from reserve_automation.web import app as web_app
    web_app.core_config = core_config
    web_app.web_config = web_config

    from reserve_automation.web.services.upload_service import UploadService
    web_app.upload_service = UploadService(
        temp_dir=web_config.uploads.temp_dir,
        max_file_size_mb=web_config.uploads.max_file_size_mb,
        allowed_extensions=web_config.uploads.allowed_extensions,
    )

    # Ensure auth config is loaded on app state
    auth_config = load_auth_config()
    app.state.auth_config = auth_config

    with TestClient(app, follow_redirects=False) as client:
        yield client


def _request(client, method, path, role="admin", **kwargs):
    """Make a request with a specific role via dev cookie."""
    cookies = {"dev_role_override": role}
    fn = getattr(client, method)
    return fn(path, cookies=cookies, **kwargs)


class TestAdminOnlyEndpoints:
    """Endpoints that should only be accessible to admin."""

    @pytest.mark.parametrize("role,expected", [
        ("admin", 200),
        ("family", 303),  # Page 403s redirect to /bottles
        ("guest", 303),
    ])
    def test_management_page(self, perm_client, role, expected):
        resp = _request(perm_client, "get", "/management", role=role)
        assert resp.status_code == expected

    @pytest.mark.parametrize("role,expected", [
        ("admin", 200),
        ("family", 303),  # Page 403s redirect to /bottles
        ("guest", 303),
    ])
    def test_upload_page(self, perm_client, role, expected):
        resp = _request(perm_client, "get", "/upload", role=role)
        assert resp.status_code == expected

    @pytest.mark.parametrize("role,expected", [
        ("admin", 200),
        ("family", 403),
        ("guest", 403),
    ])
    def test_ingredient_create(self, perm_client, role, expected):
        resp = _request(
            perm_client, "post", "/api/v1/ingredients",
            role=role,
            json={"name": f"TestIng-{role}-{uuid.uuid4().hex[:6]}"},
        )
        assert resp.status_code == expected


class TestFamilyEndpoints:
    """Endpoints accessible to admin + family but not guest."""

    @pytest.mark.parametrize("role,expected", [
        ("admin", 500),   # 500 = reached handler (no LLM configured), not 403
        ("family", 500),  # family has tastings.submit, so also reaches handler
        ("guest", 403),
    ])
    def test_tasting_card_upload(self, perm_client, role, expected):
        """POST /api/v1/tastings/upload-card requires tastings.submit."""
        import io
        # Send a minimal file upload to exercise the permission check.
        # The endpoint will fail with 500 (no LLM) for allowed roles,
        # but return 403 for denied roles.
        resp = _request(
            perm_client, "post", "/api/v1/tastings/upload-card",
            role=role,
            files={"file": ("card.jpg", io.BytesIO(b"\xff\xd8\xff\xe0"), "image/jpeg")},
        )
        assert resp.status_code == expected

    @pytest.mark.parametrize("role,expected", [
        # 404 = passed the permission check and reached the handler
        # (bottle 99999999 doesn't exist); guest must be rejected outright.
        ("admin", 404),
        ("family", 404),
        ("guest", 403),
    ])
    def test_bottle_notes_update(self, perm_client, role, expected):
        """PUT /api/v1/bottles/{id}/notes requires bottles.notes.edit (admin + family)."""
        resp = _request(
            perm_client, "put", "/api/v1/bottles/99999999/notes",
            role=role,
            json={"notes": "decant for a day"},
        )
        assert resp.status_code == expected

    @pytest.mark.parametrize("role,expected", [
        ("admin", 200),
        ("family", 200),
        ("guest", 403),
    ])
    def test_create_cocktail_event(self, perm_client, role, expected):
        resp = _request(
            perm_client, "post", "/api/v1/events/cocktail",
            role=role,
            json={
                "name": f"Test Event {role}",
                "host_name": "Tester",
                "event_mode": "flight",
            },
        )
        assert resp.status_code == expected


class TestBottlesEndpoints:
    """Bottles page and collection API accessible to all authenticated roles."""

    @pytest.mark.parametrize("role", ["admin", "family", "guest"])
    def test_bottles_page(self, perm_client, role):
        resp = _request(perm_client, "get", "/bottles", role=role)
        assert resp.status_code == 200

    @pytest.mark.parametrize("role", ["admin", "family", "guest"])
    def test_bottles_collection_api(self, perm_client, role):
        resp = _request(perm_client, "get", "/api/v1/bottles/collection", role=role)
        assert resp.status_code == 200
        data = resp.json()
        assert "bottles" in data
        assert "count" in data

    def test_root_redirects_to_bottles(self, perm_client):
        resp = _request(perm_client, "get", "/", role="guest")
        assert resp.status_code == 307
        assert resp.headers["location"] == "/bottles"


class TestPublicEndpoints:
    """Endpoints accessible to all authenticated roles."""

    @pytest.mark.parametrize("role,expected", [
        ("admin", 200),
        ("family", 200),
        ("guest", 403),  # guests can't view ingredients
    ])
    def test_ingredients_list(self, perm_client, role, expected):
        resp = _request(perm_client, "get", "/api/v1/ingredients", role=role)
        assert resp.status_code == expected

    @pytest.mark.parametrize("role", ["admin", "family", "guest"])
    def test_cocktails_list(self, perm_client, role):
        resp = _request(perm_client, "get", "/api/v1/cocktails", role=role)
        assert resp.status_code == 200

    @pytest.mark.parametrize("role", ["admin", "family", "guest"])
    def test_events_list(self, perm_client, role):
        resp = _request(perm_client, "get", "/api/v1/events", role=role)
        assert resp.status_code == 200

    @pytest.mark.parametrize("role", ["admin", "family", "guest"])
    def test_health(self, perm_client, role):
        resp = _request(perm_client, "get", "/api/v1/health", role=role)
        assert resp.status_code == 200

    @pytest.mark.parametrize("role", ["admin", "family", "guest"])
    def test_me_endpoint(self, perm_client, role):
        resp = _request(perm_client, "get", "/api/v1/me", role=role)
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == role
        assert data["authenticated"] is True


class TestGuestRestrictions:
    """Verify guests are blocked from write operations."""

    def test_guest_cannot_create_cocktail(self, perm_client):
        resp = _request(
            perm_client, "post", "/api/v1/cocktails",
            role="guest",
            json={"name": "Forbidden Cocktail", "category": "Test"},
        )
        assert resp.status_code == 403

    def test_guest_cannot_delete_event(self, perm_client):
        # First create as admin (cocktail event, no bottles needed)
        create_resp = _request(
            perm_client, "post", "/api/v1/events/cocktail",
            role="admin",
            json={
                "name": "Deletable Event",
                "host_name": "Admin",
                "event_mode": "flight",
            },
        )
        event_id = create_resp.json()["event_id"]

        # Guest cannot delete (requires events.manage)
        resp = _request(
            perm_client, "delete", f"/api/v1/events/{event_id}",
            role="guest",
        )
        assert resp.status_code == 403

    def test_guest_cannot_delete_ingredient(self, perm_client):
        # Get an ingredient ID
        list_resp = _request(perm_client, "get", "/api/v1/ingredients?flat=true", role="admin")
        ingredients = list_resp.json()
        if ingredients:
            ing_id = ingredients[0]["id"]
            resp = _request(
                perm_client, "delete", f"/api/v1/ingredients/{ing_id}",
                role="guest",
            )
            assert resp.status_code == 403
