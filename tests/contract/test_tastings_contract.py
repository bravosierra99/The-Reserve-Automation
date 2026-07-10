"""Contract fixtures for the tastings wizard, tasting review, extraction
review, and upload frontend domains.

Runs the real flows through the API with the exact payloads the frontend
sends and snapshots every response shape the four JS modules consume:

manual-tasting.js (tests/js/manual-tasting.test.js):
    tastings_autocomplete_taster_name   GET /api/v1/autocomplete/tastings/taster_name
    tastings_autocomplete_place         GET /api/v1/autocomplete/tastings/place
    tastings_autocomplete_theme         GET /api/v1/autocomplete/tastings/theme
    tastings_autocomplete_forbidden     the SAME endpoint as a guest — 403 body.
                                        The wizard is guest-facing in event mode
                                        but these endpoints require tastings.view
                                        (admin+family), so guests get this shape.
    tastings_bottle_search              GET /api/v1/bottles/search?q=&beverage_type=
                                        (candidates carry the DB id in bottle_path —
                                        the shape behind the July 2026 prod outage)
    tastings_bottle_search_wine         same, wine query
    tastings_bottle_search_event        same + &event_id= (blind-open event names
                                        are redacted to "Bottle #N")
    tastings_manual_save_obsidian       POST /api/v1/manual-tasting/save, mode
                                        "obsidian" (DB mode: file_path is the new
                                        tasting's DB id as a string, NOT a path)
    (event-mode save + wizard event detail reuse the events-domain fixtures
    manual_tasting_save_response / event_detail_blind_open / event_detail.)

review-tastings.js (tests/js/review-tastings.test.js):
    tastings_review_session             GET /api/v1/tastings/{extraction_id} (bourbon)
    tastings_review_session_wine        same for an aws_wine card
    tastings_review_match_response      POST .../{index}/match (with a real
                                        duplicate_warning from a seeded tasting)
    tastings_review_approve_response    POST .../{index}/approve
    tastings_review_skip_response       POST .../{index}/skip (last item → all_done)

review-page.js (tests/js/review-page.test.js):
    review_extraction                   GET /api/v1/extractions/{id} (bourbon)
    review_extraction_wine              same for an aws_wine card
    review_approve_response             POST /api/v1/review/{id}/approve

upload-page.js (tests/js/upload-page.test.js):
    upload_purchase_source_autocomplete GET /api/v1/autocomplete/bottles/purchase_source
    upload_verify_response              POST /api/v1/management/bottles/verify
                                        (the queued {task_id} response; the LLM
                                        background task itself is stubbed to a
                                        no-op — see comment at the capture site)

NOT contract-testable without LM Studio (JS fixtures stay hand-written,
labelled in the suites):
    POST /api/v1/tastings/upload-card                (runs a real vision extraction)
    POST /api/v1/bottles/upload/stream               (SSE stream of a real extraction)
    GET  /api/v1/management/tasks/{task_id}/status   (terminal payloads are built by
                                                     the LLM enrichment task; error
                                                     strings/timestamps are
                                                     environment-dependent)

Extraction sessions are seeded the way the real upload endpoints do it: a
signed session cookie holding `extraction_data` in the exact
ExtractionService.to_dict shape (template_type + TastingNote.model_dump
lists), created with the app's own SessionManager + secret. Everything after
that cookie — match candidates, stats, approve/skip — is computed by the real
services against the seeded bottles.

The session-mutating routes rotate the session cookie on every response (and
some set it with secure=True, which httpx won't resend over http), so the
flow tracks the token from each response's Set-Cookie header explicitly.
"""

from datetime import date

import pytest

from .contract import assert_contract

GUEST = {"dev_role_override": "guest"}

# Fixed extraction ids (UUID-shaped so the normalizer maps them like prod ids).
BOURBON_EXT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
WINE_EXT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
REVIEW_EXT_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
REVIEW_WINE_EXT_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


# The wizard initializes every key of tastingData and sends the full object
# (see manual-tasting.js tastingData / resetTastingData).
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


def _extracted_note(**kwargs):
    """A TastingNote dict exactly as ExtractionService.to_dict serializes it."""
    from reserve_automation.core.tasting_note import TastingNote

    return TastingNote(**kwargs).model_dump(mode="json")


def _session_manager():
    from reserve_automation.web.config import load_web_config
    from reserve_automation.web.sessions import SessionManager

    _, web_config = load_web_config()
    return SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours,
    )


def _rotated_token(response, current):
    """Track the session token the API rotates via Set-Cookie on every write."""
    for header in response.headers.get_list("set-cookie"):
        if not header.startswith("session="):
            continue
        value = header.split(";", 1)[0].split("=", 1)[1].strip('"')
        return value or None  # delete_cookie emits session=""
    return current


def _forget_jar_session(client):
    """Drop any session cookie httpx stored — tokens are passed explicitly."""
    try:
        client.cookies.delete("session")
    except KeyError:
        pass


@pytest.fixture(scope="module")
def tastings_flow(contract_client, contract_db):
    """Run every flow once against a wiped DB; return the captured responses."""
    from unittest.mock import patch

    from reserve_automation.core.models import BottleMetadata
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository

    client = contract_client
    repo = SQLiteBottleRepository(contract_db)
    weller = repo.create(BottleMetadata(
        producer="Buffalo Trace", name="Weller Special Reserve",
        type="whiskey", source="test", proof=90, region="Kentucky",
        purchase_source="Total Wine", inventory=1,
    ))
    willett = repo.create(BottleMetadata(
        producer="Willett", name="Pot Still Reserve",
        type="whiskey", source="test", proof=94, region="Kentucky",
        purchase_source="Seelbach's", inventory=1,
    ))
    caymus = repo.create(BottleMetadata(
        producer="Caymus Vineyards", name="Cabernet Sauvignon",
        type="wine", source="test", year=2021, region="USA - Napa Valley",
        purchase_source="Total Wine", inventory=1,
    ))
    captured = {}

    # ---- Manual tasting wizard: non-event ("obsidian") save --------------
    # Exact saveRequest shape from manual-tasting.js saveTasting(): the DB
    # bottle id goes in BOTH bottle fields (search candidates carry it in
    # bottle_path). Also seeds taster/place/theme for the autocomplete
    # fixtures and the duplicate-warning capture below (Ben + 2026-07-07 +
    # bottle 1).
    save = client.post("/api/v1/manual-tasting/save", json={
        "mode": "obsidian",
        "beverage_type": "whiskey",
        "taster_name": "Ben",
        "tasting_date": "2026-07-07",
        "selected_bottle_id": str(weller.id),
        "selected_bottle_path": str(weller.id),
        "tasting_data": _wizard_tasting_data(
            place="The Study", theme="Wheated Night",
            whiskey_nose=3, whiskey_palate=3, whiskey_finish=2,
            whiskey_overall=1,
            nose_notes=["caramel", "oak"], palate_notes=["cherry"],
            finish_notes=["long"], overall_notes="Excellent wheater",
        ),
    })
    assert save.status_code == 200, save.text
    captured["tastings_manual_save_obsidian"] = save.json()

    save2 = client.post("/api/v1/manual-tasting/save", json={
        "mode": "obsidian",
        "beverage_type": "wine",
        "taster_name": "Sarah",
        "tasting_date": "2026-07-06",
        "selected_bottle_id": str(caymus.id),
        "selected_bottle_path": str(caymus.id),
        "tasting_data": _wizard_tasting_data(
            place="Back Porch", theme="Napa Cabs",
            wine_appearance=2, wine_aroma=5, wine_taste=4,
            wine_aftertaste=2, wine_overall=1.5,
            appearance_notes=["ruby"], nose_notes=["cherry"],
            palate_notes=["plum"], finish_notes=["long"],
            overall_notes="Lovely",
        ),
    })
    assert save2.status_code == 200, save2.text

    # ---- Wizard autocomplete (admin sees values; guests get 403) ----------
    for field in ("taster_name", "place", "theme"):
        resp = client.get(f"/api/v1/autocomplete/tastings/{field}")
        assert resp.status_code == 200, resp.text
        captured[f"tastings_autocomplete_{field}"] = resp.json()

    forbidden = client.get(
        "/api/v1/autocomplete/tastings/taster_name", cookies=GUEST
    )
    assert forbidden.status_code == 403, forbidden.text
    captured["tastings_autocomplete_forbidden"] = forbidden.json()

    # ---- Wizard bottle search (exact URLs manual-tasting.js builds) -------
    search = client.get("/api/v1/bottles/search?q=weller&beverage_type=whiskey")
    assert search.status_code == 200, search.text
    assert search.json()["results"], "search must return candidates"
    captured["tastings_bottle_search"] = search.json()

    wine_search = client.get("/api/v1/bottles/search?q=caymus&beverage_type=wine")
    assert wine_search.status_code == 200, wine_search.text
    assert wine_search.json()["results"]
    captured["tastings_bottle_search_wine"] = wine_search.json()

    # Event-scoped search: guests search within a blind open event and get
    # redacted "Bottle #N" names with the bottle id in bottle_path.
    create = client.post("/api/v1/events", json={
        "name": "Contract Tastings Night",
        "beverage_type": "whiskey",
        "is_blind": True,
        "host_name": "Ben",
        "bottle_ids": [str(weller.id), str(willett.id)],
        "blind_numbers": [1, 2],
    })
    assert create.status_code == 200, create.text
    event_id = create.json()["event_id"]
    join = client.post(
        f"/api/v1/events/{event_id}/join",
        json={"participant_name": "Alice"},
        cookies=GUEST,
    )
    assert join.status_code == 200, join.text

    event_search = client.get(
        f"/api/v1/bottles/search?q=special&beverage_type=whiskey&event_id={event_id}",
        cookies=GUEST,
    )
    assert event_search.status_code == 200, event_search.text
    assert event_search.json()["results"]
    captured["tastings_bottle_search_event"] = event_search.json()

    # ---- Tasting review page (review-tastings.js) -------------------------
    # Seed the extraction session the way upload-card does (signed cookie with
    # extraction_data); the GET builds the real TastingSession from it, running
    # real matching against the seeded bottles.
    sm = _session_manager()
    bourbon_extraction = {
        "template_type": "bourbon",
        "tastings": [
            _extracted_note(
                bottle_name="Weller Special Reserve", taster_name="Ben",
                tasting_date=date(2026, 7, 7), beverage_type="whiskey",
                whiskey_nose=2.5, whiskey_palate=2.5, whiskey_finish=2,
                whiskey_overall=0.8,
                nose_notes=["caramel", "oak"], palate_notes=["cherry"],
                finish_notes=[], overall_notes="Great pour",
                days_from_crack=30, fill_level=80,
            ),
            _extracted_note(
                bottle_name="Mystery Bourbon", taster_name="",
                tasting_date=date(2026, 7, 7), beverage_type="whiskey",
                whiskey_nose=1, whiskey_palate=1, whiskey_finish=1,
                whiskey_overall=0.5,
            ),
        ],
    }
    token = sm.create_session({
        "extraction_id": BOURBON_EXT_ID,
        "upload_filename": "tasting-card.jpg",
        "extraction_data": bourbon_extraction,
        "expected_count": 2,
    })

    session_resp = client.get(
        f"/api/v1/tastings/{BOURBON_EXT_ID}", cookies={"session": token}
    )
    assert session_resp.status_code == 200, session_resp.text
    captured["tastings_review_session"] = session_resp.json()
    token = _rotated_token(session_resp, token)
    _forget_jar_session(client)

    # Match tasting 0 to the Weller — Ben already tasted it on 2026-07-07
    # (seeded above), so this captures a real duplicate_warning.
    match = client.post(
        f"/api/v1/tastings/{BOURBON_EXT_ID}/0/match",
        json={"bottle_path": str(weller.id)},
        cookies={"session": token},
    )
    assert match.status_code == 200, match.text
    captured["tastings_review_match_response"] = match.json()
    token = _rotated_token(match, token)
    _forget_jar_session(client)

    approve = client.post(
        f"/api/v1/tastings/{BOURBON_EXT_ID}/0/approve",
        cookies={"session": token},
    )
    assert approve.status_code == 200, approve.text
    captured["tastings_review_approve_response"] = approve.json()
    token = _rotated_token(approve, token)
    _forget_jar_session(client)

    skip = client.post(
        f"/api/v1/tastings/{BOURBON_EXT_ID}/1/skip",
        cookies={"session": token},
    )
    assert skip.status_code == 200, skip.text
    captured["tastings_review_skip_response"] = skip.json()
    _forget_jar_session(client)

    # Wine (aws_wine) session — separate rendering path (isWine getter).
    # Tasting 0 has an empty taster_name (exercises the participant-cookie
    # auto-fill in the JS); tasting 1 has no matching bottle in the DB.
    wine_extraction = {
        "template_type": "aws_wine",
        "tastings": [
            _extracted_note(
                bottle_name="Cabernet Sauvignon", taster_name="",
                tasting_date=date(2026, 7, 7), beverage_type="wine",
                wine_appearance=3, wine_aroma=5, wine_taste=4,
                wine_aftertaste=1.5, wine_overall=1.5,
                appearance_notes=["ruby"], nose_notes=["cassis"],
                palate_notes=["plum"], finish_notes=["long"],
                overall_notes="Lovely",
            ),
            _extracted_note(
                bottle_name="Mystery Red", taster_name="Sarah",
                tasting_date=date(2026, 7, 7), beverage_type="wine",
                wine_appearance=2, wine_aroma=3, wine_taste=3,
                wine_aftertaste=1, wine_overall=1,
            ),
        ],
    }
    wine_token = sm.create_session({
        "extraction_id": WINE_EXT_ID,
        "upload_filename": "wine-card.jpg",
        "extraction_data": wine_extraction,
        "expected_count": None,
    })
    wine_session = client.get(
        f"/api/v1/tastings/{WINE_EXT_ID}", cookies={"session": wine_token}
    )
    assert wine_session.status_code == 200, wine_session.text
    captured["tastings_review_session_wine"] = wine_session.json()
    _forget_jar_session(client)

    # ---- Extraction review page (review-page.js) --------------------------
    review_token = sm.create_session({
        "extraction_id": REVIEW_EXT_ID,
        "upload_filename": "card.jpg",
        "extraction_data": bourbon_extraction,
    })
    extraction_resp = client.get(
        f"/api/v1/extractions/{REVIEW_EXT_ID}", cookies={"session": review_token}
    )
    assert extraction_resp.status_code == 200, extraction_resp.text
    captured["review_extraction"] = extraction_resp.json()

    review_wine_token = sm.create_session({
        "extraction_id": REVIEW_WINE_EXT_ID,
        "upload_filename": "wine-card.jpg",
        "extraction_data": wine_extraction,
    })
    extraction_wine = client.get(
        f"/api/v1/extractions/{REVIEW_WINE_EXT_ID}",
        cookies={"session": review_wine_token},
    )
    assert extraction_wine.status_code == 200, extraction_wine.text
    captured["review_extraction_wine"] = extraction_wine.json()

    # Approve flow exactly as review-page.js does it: PUT the (edited) data —
    # including the *_str editing fields loadExtraction() added, which the
    # frontend sends back verbatim — then POST approve.
    edited = extraction_resp.json()["data"]
    for tasting in edited["tastings"]:
        tasting["nose_notes_str"] = ", ".join(tasting.get("nose_notes") or [])
        tasting["palate_notes_str"] = ", ".join(tasting.get("palate_notes") or [])
        tasting["finish_notes_str"] = ", ".join(tasting.get("finish_notes") or [])
    put = client.put(
        f"/api/v1/extractions/{REVIEW_EXT_ID}",
        json={"extraction_data": edited},
        cookies={"session": review_token},
    )
    assert put.status_code == 200, put.text
    review_token = _rotated_token(put, review_token)
    _forget_jar_session(client)

    review_approve = client.post(
        f"/api/v1/review/{REVIEW_EXT_ID}/approve",
        cookies={"session": review_token},
    )
    assert review_approve.status_code == 200, review_approve.text
    captured["review_approve_response"] = review_approve.json()
    _forget_jar_session(client)

    # ---- Import page (upload-page.js) -------------------------------------
    ac = client.get("/api/v1/autocomplete/bottles/purchase_source")
    assert ac.status_code == 200, ac.text
    captured["upload_purchase_source_autocomplete"] = ac.json()

    # POST /api/v1/management/bottles/verify queues an LLM enrichment task and
    # returns {task_id, status} BEFORE the task runs. TestClient executes
    # background tasks synchronously after the response is built, so the real
    # enrichment (web search + LM Studio) is stubbed to a no-op — the captured
    # response is produced entirely by the route itself. The task's terminal
    # /status payload IS LLM-built and stays hand-written in the JS suite.
    with patch(
        "reserve_automation.web.routes.management.core.verify_single_bottle_background"
    ):
        verify = client.post("/api/v1/management/bottles/verify", json={
            # Exact body enrichManifestBottle() sends: _-prefixed fields
            # stripped, numeric empty strings nulled.
            "bottle": {
                "producer": "Buffalo Trace", "name": "Weller Special Reserve",
                "type": "whiskey", "year": None, "price": None,
                "abv": None, "proof": None, "inventory": None,
            },
        })
    assert verify.status_code == 200, verify.text
    captured["upload_verify_response"] = verify.json()

    return captured


# ---- manual-tasting.js -----------------------------------------------------

def test_tastings_manual_save_obsidian_contract(tastings_flow):
    assert_contract(
        "tastings_manual_save_obsidian",
        tastings_flow["tastings_manual_save_obsidian"],
    )


def test_tastings_autocomplete_taster_name_contract(tastings_flow):
    assert_contract(
        "tastings_autocomplete_taster_name",
        tastings_flow["tastings_autocomplete_taster_name"],
    )


def test_tastings_autocomplete_place_contract(tastings_flow):
    assert_contract(
        "tastings_autocomplete_place", tastings_flow["tastings_autocomplete_place"]
    )


def test_tastings_autocomplete_theme_contract(tastings_flow):
    assert_contract(
        "tastings_autocomplete_theme", tastings_flow["tastings_autocomplete_theme"]
    )


def test_tastings_autocomplete_forbidden_contract(tastings_flow):
    # 403 body guests receive from the wizard's autocomplete fetches.
    assert_contract(
        "tastings_autocomplete_forbidden",
        tastings_flow["tastings_autocomplete_forbidden"],
    )


def test_tastings_bottle_search_contract(tastings_flow):
    assert_contract(
        "tastings_bottle_search", tastings_flow["tastings_bottle_search"]
    )


def test_tastings_bottle_search_wine_contract(tastings_flow):
    assert_contract(
        "tastings_bottle_search_wine", tastings_flow["tastings_bottle_search_wine"]
    )


def test_tastings_bottle_search_event_contract(tastings_flow):
    assert_contract(
        "tastings_bottle_search_event",
        tastings_flow["tastings_bottle_search_event"],
    )


# ---- review-tastings.js -----------------------------------------------------

def test_tastings_review_session_contract(tastings_flow):
    assert_contract(
        "tastings_review_session", tastings_flow["tastings_review_session"]
    )


def test_tastings_review_session_wine_contract(tastings_flow):
    assert_contract(
        "tastings_review_session_wine",
        tastings_flow["tastings_review_session_wine"],
    )


def test_tastings_review_match_response_contract(tastings_flow):
    assert_contract(
        "tastings_review_match_response",
        tastings_flow["tastings_review_match_response"],
    )


def test_tastings_review_approve_response_contract(tastings_flow):
    assert_contract(
        "tastings_review_approve_response",
        tastings_flow["tastings_review_approve_response"],
    )


def test_tastings_review_skip_response_contract(tastings_flow):
    assert_contract(
        "tastings_review_skip_response",
        tastings_flow["tastings_review_skip_response"],
    )


# ---- review-page.js ----------------------------------------------------------

def test_review_extraction_contract(tastings_flow):
    assert_contract("review_extraction", tastings_flow["review_extraction"])


def test_review_extraction_wine_contract(tastings_flow):
    assert_contract(
        "review_extraction_wine", tastings_flow["review_extraction_wine"]
    )


def test_review_approve_response_contract(tastings_flow):
    assert_contract(
        "review_approve_response", tastings_flow["review_approve_response"]
    )


# ---- upload-page.js -----------------------------------------------------------

def test_upload_purchase_source_autocomplete_contract(tastings_flow):
    assert_contract(
        "upload_purchase_source_autocomplete",
        tastings_flow["upload_purchase_source_autocomplete"],
    )


def test_upload_verify_response_contract(tastings_flow):
    assert_contract(
        "upload_verify_response", tastings_flow["upload_verify_response"]
    )
