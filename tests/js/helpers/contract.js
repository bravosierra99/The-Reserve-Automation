/**
 * Loader for the shared contract fixtures in tests/fixtures/contract/.
 *
 * These JSON files are real API responses captured (and snapshot-verified on
 * every pytest run) by tests/contract/ — see tests/contract/contract.py for
 * the full rationale. JS tests MUST source their "this is what the API
 * returns" fixtures from here instead of hand-writing them: hand-written
 * fixtures encode the test author's assumptions, and a wrong shared
 * assumption passes on both sides (July 2026: event-results rendered
 * undefined in prod behind a green 38-test suite built on invented fixtures).
 *
 * Each call returns a fresh deep clone — mutate freely for per-test variants,
 * but keep variants as explicit mutations of the loaded object so the shape
 * itself always comes from the contract.
 *
 * // #CLAUDE_REQ: FIXTURE_DIR must match tests/contract/contract.py.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const FIXTURE_DIR = join(
    dirname(fileURLToPath(import.meta.url)), '..', '..', 'fixtures', 'contract'
);

export function loadContract(name) {
    const raw = readFileSync(join(FIXTURE_DIR, `${name}.json`), 'utf-8');
    return JSON.parse(raw);
}
