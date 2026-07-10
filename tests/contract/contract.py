"""Contract-fixture harness: one JSON file per API response shape, shared
verbatim between the Python API tests (producer side) and the vitest JS
suites (consumer side).

Why this exists (July 2026 postmortem): the event-results page and the
tasting-save endpoint each shipped with green tests because both sides were
tested against fixtures written by the same hand as the code — a shared wrong
assumption passed everywhere. These fixtures are the mechanical tie-break:
the Python test *captures a real response* from a real flow and snapshots it
to tests/fixtures/contract/<name>.json; the JS tests load that same file as
their fixture (tests/js/helpers/contract.js). If the API shape drifts, the
Python snapshot test fails; if the JS code reads fields the API doesn't
produce, its fixture no longer carries them and the JS test fails.

Usage (producer side):

    data = client.get(f"/api/v1/events/{event_id}").json()
    assert_contract("event_detail", data)

Regenerating after an intentional API change:

    UPDATE_CONTRACT_FIXTURES=1 uv run pytest tests/contract/
    # then re-run the JS suites — they consume the same files:
    npx vitest run

Determinism: contract test modules must start from an empty database (use the
`contract_db` fixture from tests/contract/conftest.py, which wipes every
table — SQLite then restarts integer PKs at 1) and use fixed dates in request
payloads. The two genuinely uncontrollable values are normalized before
snapshotting: UUID strings (mapped to stable placeholders in first-encounter
order, per fixture) and ISO datetime strings (flattened to a fixed instant).
Everything else — field names, nesting, int-vs-string types, key order — is
snapshotted exactly as the API returned it, because that IS the contract.
"""

import json
import os
import re
from pathlib import Path

import pytest

# #CLAUDE_REQ: tests/js/helpers/contract.js reads the same directory — if this
# path moves, move it there too.
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "contract"

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
# Datetime *with a time component*. Date-only strings (e.g. tasting_date) come
# from fixed test inputs and pass through untouched.
_ISO_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
_FIXED_DT = "2026-07-07T19:00:00"


def _norm_scalar(value: str, uuid_map: dict[str, str]) -> str:
    if _UUID_RE.match(value):
        if value not in uuid_map:
            uuid_map[value] = f"00000000-0000-4000-8000-{len(uuid_map) + 1:012d}"
        return uuid_map[value]
    if _ISO_DT_RE.match(value):
        return _FIXED_DT
    return value


def _normalize(value, uuid_map: dict[str, str]):
    if isinstance(value, dict):
        return {
            (_norm_scalar(k, uuid_map) if isinstance(k, str) else k): _normalize(
                v, uuid_map
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_normalize(v, uuid_map) for v in value]
    if isinstance(value, str):
        return _norm_scalar(value, uuid_map)
    return value


def assert_contract(name: str, payload) -> None:
    """Snapshot-assert an API response against tests/fixtures/contract/<name>.json.

    With UPDATE_CONTRACT_FIXTURES=1 the fixture is (re)written instead, and the
    assertion then runs against the fresh file — so a regen run still fails if
    the flow is non-deterministic between capture and compare.

    UUID placeholders are assigned per fixture (fresh map per call): a fixture
    is internally consistent, but the same real UUID may map differently in two
    different fixture files. JS tests that need cross-fixture identity should
    patch the IDs explicitly.
    """
    normalized = _normalize(payload, {})
    path = FIXTURE_DIR / f"{name}.json"

    if os.environ.get("UPDATE_CONTRACT_FIXTURES"):
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if not path.exists():
        pytest.fail(
            f"Contract fixture missing: {path}. Generate it with\n"
            f"  UPDATE_CONTRACT_FIXTURES=1 uv run pytest tests/contract/"
        )

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    if normalized == on_disk:
        return
    import difflib

    diff = "\n".join(difflib.unified_diff(
        json.dumps(on_disk, indent=2, ensure_ascii=False).splitlines(),
        json.dumps(normalized, indent=2, ensure_ascii=False).splitlines(),
        fromfile=f"fixture {name}.json",
        tofile="live API response (normalized)",
        lineterm="",
    ))
    pytest.fail(
        f"API response no longer matches contract fixture '{name}.json'.\n"
        f"{diff}\n"
        f"If the API change is intentional: regenerate with\n"
        f"  UPDATE_CONTRACT_FIXTURES=1 uv run pytest tests/contract/\n"
        f"then run the JS suites (npx vitest run) — they consume this same "
        f"file, so any frontend code reading the old shape will now fail "
        f"loudly instead of rendering undefined in prod.\n"
        f"If the change is NOT intentional, you just caught a contract break.",
        pytrace=False,
    )


def wipe_database(db) -> None:
    """Delete every row from every table (FK-safe order).

    Contract tests must start from an empty DB so integer PKs restart at 1 and
    snapshots are deterministic regardless of which other suites ran first.
    """
    from reserve_automation.db.base import Base

    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()
