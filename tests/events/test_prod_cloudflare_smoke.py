"""
Opt-in smoke test: exercise the event lifecycle on PROD through Cloudflare.

Authenticates with the standing CF Access service token (the app maps its
client ID to the admin role — see config/auth.yaml). Creates a throwaway
blind event on the live server, adds a bottle mid-event, reveals, checks
results, and deletes it. Touches real prod data only via that one event.

Never runs by default. To run:

    RUN_PROD_SMOKE=1 uv run --env-file .env pytest tests/events/test_prod_cloudflare_smoke.py -v

Requires CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET in the environment
(both live in automation/.env; scripts/agent.py uses the same credentials).
"""

import os

import httpx
import pytest

PROD_URL = os.environ.get("PROD_SMOKE_URL", "https://reserve.teamsmith.xyz")

pytestmark = [
    pytest.mark.prod_smoke,
    pytest.mark.skipif(
        os.environ.get("RUN_PROD_SMOKE") != "1"
        or not os.environ.get("CF_ACCESS_CLIENT_ID")
        or not os.environ.get("CF_ACCESS_CLIENT_SECRET"),
        reason="prod smoke is opt-in: set RUN_PROD_SMOKE=1 and CF Access "
        "service-token credentials (see module docstring)",
    ),
]


@pytest.fixture(scope="module")
def cf_client():
    """HTTP client that authenticates through Cloudflare Access."""
    headers = {
        "CF-Access-Client-Id": os.environ["CF_ACCESS_CLIENT_ID"],
        "CF-Access-Client-Secret": os.environ["CF_ACCESS_CLIENT_SECRET"],
    }
    with httpx.Client(base_url=PROD_URL, headers=headers, timeout=30) as client:
        yield client


@pytest.fixture(scope="module")
def prod_bottle_ids(cf_client):
    """Two real bottle IDs from the live collection (read-only)."""
    response = cf_client.get("/api/v1/bottles/search", params={"q": "a"})
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert len(results) >= 2, "prod collection has fewer than 2 searchable bottles"
    return [results[0]["bottle_path"], results[1]["bottle_path"]]


def test_service_token_maps_to_admin(cf_client):
    """The CF service token must authenticate as the admin role, not guest."""
    response = cf_client.get("/api/v1/me")
    assert response.status_code == 200, response.text
    me = response.json()
    assert me["authenticated"] is True
    assert me["role"] == "admin"
    assert me["dev_mode"] is False  # real Cloudflare JWT path, not LAN bypass


def test_event_lifecycle_through_cloudflare(cf_client, prod_bottle_ids):
    """Create → add bottle mid-event → reveal → results → delete, all via CF."""
    first, second = prod_bottle_ids
    event_id = None
    try:
        create = cf_client.post(
            "/api/v1/events",
            json={
                "name": "PROD SMOKE TEST - auto-deleted",
                "beverage_type": "wine",
                "is_blind": True,
                "host_name": "CF Smoke Test",
                "bottle_ids": [first],
                "blind_numbers": [1],
            },
        )
        assert create.status_code == 200, create.text
        event_id = create.json()["event_id"]

        add = cf_client.post(
            f"/api/v1/events/{event_id}/bottles",
            json={"bottle_id": second},
        )
        assert add.status_code == 200, add.text
        added = add.json()["bottle"]
        assert added["blind_number"] == 2
        # The add response never echoes the identity on a blind open event
        assert added["bottle_name"] == "Bottle #2"

        reveal = cf_client.put(f"/api/v1/events/{event_id}/reveal")
        assert reveal.status_code == 200, reveal.text
        assert reveal.json()["event"]["status"] == "revealed"

        results_page = cf_client.get(f"/events/{event_id}/results")
        assert results_page.status_code == 200
    finally:
        if event_id:
            delete = cf_client.delete(f"/api/v1/events/{event_id}")
            assert delete.status_code == 200, delete.text
            assert cf_client.get(f"/api/v1/events/{event_id}").status_code == 404
