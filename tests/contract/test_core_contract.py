"""Contract fixtures shared by nearly every page module.

    me        GET /api/v1/me  (base-page.js, bottles-page.js, event-detail.js,
              management-app.js, bottle-editor-modal.js)
    me_guest  same endpoint as the guest role — pages branch on role/permissions
"""

from .contract import assert_contract


def test_me_contract(contract_client):
    response = contract_client.get("/api/v1/me")
    assert response.status_code == 200, response.text
    assert_contract("me", response.json())


def test_me_guest_contract(contract_client):
    response = contract_client.get(
        "/api/v1/me", cookies={"dev_role_override": "guest"}
    )
    assert response.status_code == 200, response.text
    assert_contract("me_guest", response.json())
