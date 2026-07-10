# Contract fixture tests

**What these are:** each JSON file in `tests/fixtures/contract/` is a *real API
response*, captured from a real user flow run through the FastAPI TestClient
and snapshot-verified on every pytest run. The vitest JS suites load the exact
same files as their fixtures (`tests/js/helpers/contract.js`). The fixture
files are the mechanical tie between backend and frontend tests.

**Why (July 2026 postmortem):** the event-results page shipped broken behind a
green 38-test vitest suite, and the tasting-save endpoint rejected the real
wizard payload behind green API tests. Both sides were tested against fixtures
hand-written by the same author as the code — a shared wrong assumption passed
everywhere. With contract fixtures, a shape drift breaks the Python snapshot;
JS code reading fields the API doesn't produce breaks the JS test.

## Layout

- `contract.py` — `assert_contract(name, payload)` (snapshot assert +
  normalization) and `wipe_database(db)`. Read its docstring first.
- `conftest.py` — `contract_db` (wiped DB, module-scoped) and
  `contract_client` (TestClient) fixtures.
- `test_<domain>_contract.py` — one file per domain; runs the real flow via
  the API and captures responses.
- `../fixtures/contract/*.json` — the checked-in snapshots (do not hand-edit).
- `../js/helpers/contract.js` — `loadContract(name)` for vitest suites.

## Running

```bash
uv run pytest tests/contract/            # verify snapshots against live API
UPDATE_CONTRACT_FIXTURES=1 uv run pytest tests/contract/   # regenerate
npx vitest run                           # JS consumers of the same files
```

After an intentional API-shape change: regenerate, then run the JS suites —
failures there are the frontend telling you what it depended on.

## Writing a new contract test

1. Use `contract_client` + `contract_db`; seed data via repositories, then
   drive everything through the API **with the exact payloads the frontend
   sends** (read the JS module's fetch calls — do not POST what the server
   schema wishes it received).
2. Use fixed dates/inputs. UUIDs and datetimes are normalized automatically;
   anything else volatile means your flow is non-deterministic — fix the flow
   (or the API: e.g. event participants needed an `order_by`), don't hack the
   normalizer.
3. Run the regen command, then run the plain verify **twice** — it must pass
   both times, and also when other suites run first
   (`uv run pytest tests/events/ tests/contract/`).
4. In the vitest suite, `loadContract('<name>')` for the base shape; per-test
   variants are explicit mutations of that object. Hand-written fixtures are
   only for shapes the current API can no longer produce (label them legacy).

## Known limits

- Fixtures capture shape at one point of the flow; they don't replace e2e.
- UUID placeholders are per-fixture (fresh map per file) — the same real UUID
  can map differently across two fixture files.
- LLM-dependent endpoints (extraction/upload) can only be contract-tested to
  the extent their records can be seeded without LM Studio; anything else is
  documented in the domain test file.
