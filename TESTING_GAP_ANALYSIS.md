# Testing Gap Analysis Report
**Spirits Automation Application**
**Generated**: 2025-12-27
**Analysis Scope**: Unit, Integration, and Functional Testing Coverage

---

## Executive Summary

### Current State
- **81 unit tests** across 4 modules (extractors, generators, LLM gateway, parsers)
- **Integration tests**: CLI and web bottle extraction (2 modules)
- **Functional tests**: Event system (4 tests), tasting workflows (3 suites), UI tests
- **Test pyramid status**: ⚠️ **INVERTED** - More functional/integration tests than unit tests

### Critical Findings
1. **Zero service layer unit tests** - 1,733 LOC in `web/services/*.py` untested
2. **No model validation tests** - BottleMetadata and TastingNote schema coherence unchecked
3. **Web route handlers untested** - 3,985 LOC of API endpoints without coverage
4. **Missing cross-cutting tests** - Duplicate detection, bottle matching, vault operations
5. **Appearance_notes field regression** - No tests caught missing field across 5 files

### Risk Assessment
- **HIGH**: Service layer (tasting_service.py - 727 LOC, complex business logic)
- **HIGH**: Model/schema coherence (recent appearance_notes bug demonstrates gap)
- **MEDIUM**: Web routes (API contracts, error handling, session management)
- **MEDIUM**: Utility modules (bottle_matcher, vault_reader, obsidian_updater)
- **LOW**: Already covered (extractors, parsers, generators)

---

## 1. Current Coverage Summary

### Unit Tests (81 tests)
```
tests/unit/
├── test_extractors.py      (39 tests) ✅ Comprehensive
├── test_generators.py      (19 tests) ✅ Good coverage
├── test_llm_gateway.py     (8 tests)  ✅ Routing/fallback
└── test_parsers.py         (15 tests) ✅ PDF/Image parsing
```

**Strengths**:
- Excellent extraction pipeline coverage
- Good confidence calculation tests
- Mock-based LLM testing
- Parser edge cases covered

**Weaknesses**:
- Limited to core data flow
- No service layer tests
- No web framework tests
- No database/vault integration tests

### Integration Tests (2 modules)
```
tests/
├── test_bottle_extraction_cli.py   ✅ E2E CLI workflow
└── test_bottle_extraction_web.py   ✅ E2E Web workflow
```

**Strengths**:
- End-to-end validation
- Real file uploads tested

**Weaknesses**:
- Only covers extraction workflow
- Doesn't test tasting workflow
- No event system integration tests

### Functional Tests (7+ test suites)
```
tests/events/
├── test_edit_tasting.py       ✅ Edit workflow
└── test_multi_event.py        ✅ Multi-participant

tests/tastings/
├── test_event_tastings.py     ✅ Event mode
├── test_cli_extraction.py     ✅ CLI extraction
├── test_vault_integration.py  ✅ Vault writes
└── test_manual_tasting_ui.py  ✅ UI readonly regression
```

**Strengths**:
- Good UI regression coverage
- Event workflow validated
- Catches field visibility bugs

**Weaknesses**:
- Manual execution required
- No automated CI integration
- Overlaps with unit test domain

---

## 2. Critical Testing Gaps (Priority Order)

### Priority 1: Service Layer Tests 🔴 CRITICAL

**Impact**: 1,733 LOC of complex business logic untested

#### Missing Coverage

##### A. `tasting_service.py` (727 LOC)
**Untested functions**:
- `create_session_from_extraction()` - Session creation logic
- `get_match_candidates()` - Bottle matching with event filtering
- `search_bottles()` - Search with fuzzy/strict matching
- `check_duplicate_tasting()` - Duplicate detection by taster/date
- `save_tasting()` - Vault writes with error handling
- `_tasting_note_to_data()` / `_data_to_tasting_note()` - Data conversion

**Recent bugs this would catch**:
- ✅ appearance_notes field missing from conversion methods
- ✅ Wine showing whiskey fields (type validation)
- ✅ Event bottle filtering edge cases

**Test examples needed**:
```python
# Test 1: Session creation with type validation
def test_create_session_wine_only_has_wine_fields():
    """Ensure wine tastings don't get whiskey fields"""
    extraction = TastingExtractionResult(
        tastings=[wine_tasting],
        template_type="aws_wine"
    )
    session = service.create_session_from_extraction("id1", extraction)

    assert session.tastings[0].tasting_data.wine_appearance is not None
    assert session.tastings[0].tasting_data.whiskey_nose is None  # Should not bleed

# Test 2: Duplicate detection
def test_check_duplicate_tasting_same_date_taster():
    """Catch duplicate tasting by same taster on same date"""
    # Setup: Create existing tasting file in temp vault
    existing = create_tasting_file(
        bottle_path="1_Whiskeys/Stagg",
        taster="Alice",
        date="2025-12-27"
    )

    warning = service.check_duplicate_tasting(
        bottle_path="1_Whiskeys/Stagg",
        taster="Alice",
        tasting_date=date(2025, 12, 27)
    )

    assert warning is not None
    assert "Alice" in warning
    assert "2025-12-27" in warning

# Test 3: Event bottle filtering
def test_get_match_candidates_event_bottles_only():
    """When event_id provided, only return event bottles"""
    event_id = create_event_with_bottles(["Stagg", "EH Taylor"])

    # Search for "Blanton's" which is NOT in event
    candidates = service.get_match_candidates(
        bottle_name="Blanton's",
        beverage_type="whiskey",
        event_id=event_id
    )

    assert len(candidates) == 0  # Should not find non-event bottles

# Test 4: appearance_notes field coherence
def test_tasting_note_conversion_preserves_appearance_notes():
    """Ensure appearance_notes survives round-trip conversion"""
    original = TastingNote(
        bottle_name="Test Wine",
        taster_name="Tester",
        tasting_date=date.today(),
        beverage_type="wine",
        appearance_notes=["ruby", "clear", "viscous"]
    )

    data = service._tasting_note_to_data(original)
    assert data.appearance_notes == ["ruby", "clear", "viscous"]

    converted_back = service._data_to_tasting_note(data)
    assert converted_back.appearance_notes == ["ruby", "clear", "viscous"]
```

##### B. `duplicate_service.py` (303 LOC)
**Untested functions**:
- `find_potential_duplicates()` - Fuzzy matching logic
- `_calculate_similarity()` - Multi-strategy matching
- `_try_structured_match()` - Parse "Producer - Name - Year" format

**Edge cases to test**:
```python
def test_duplicate_detection_year_format_variations():
    """Test matching bottles with different year formats"""
    bottle = BottleMetadata(
        producer="Caymus",
        name="Cabernet Sauvignon",
        year=2019,
        type="wine"
    )

    # Should match all these variations:
    # - "Caymus - Cabernet Sauvignon (2019).md"
    # - "Caymus - Cabernet Sauvignon - 2019.md"
    # - "Caymus - Cabernet Sauvignon 2019.md"

    duplicates = service.find_potential_duplicates(bottle, threshold=0.8)
    assert len(duplicates) >= 3

def test_duplicate_detection_threshold_boundary():
    """Test that similarity threshold works correctly"""
    bottle = BottleMetadata(
        producer="Buffalo Trace",
        name="Bourbon",
        type="whiskey"
    )

    high_threshold = service.find_potential_duplicates(bottle, threshold=0.9)
    low_threshold = service.find_potential_duplicates(bottle, threshold=0.5)

    assert len(low_threshold) >= len(high_threshold)
```

##### C. `extraction_service.py` (261 LOC)
**Untested functions**:
- `extract_from_image()` - Image processing pipeline
- `from_dict()` - Deserialization (used in session recovery)

##### D. Other services
- `upload_service.py` (164 LOC) - File handling, temp file cleanup
- `review_service.py` (169 LOC) - Review workflow coordination
- `label_service.py` (109 LOC) - Label image processing

---

### Priority 2: Model/Schema Coherence Tests 🔴 CRITICAL

**Impact**: Prevents regressions like the appearance_notes bug

#### A. Field Coherence Across Components

**The appearance_notes Bug Demonstrated This Gap**:
```
Field was missing from:
1. TastingData schema (web/schemas/tasting.py)
2. Manual session conversion (tasting_service.py)
3. Template rendering (generators/tasting_generator.py)
4. HTML form (templates/manual_tasting.html)
```

**Test needed**:
```python
def test_tasting_note_fields_match_across_all_components():
    """Ensure all components have same field set for each beverage type"""
    from reserve_automation.core.tasting_note import TastingNote
    from reserve_automation.web.schemas.tasting import TastingData

    # Get all fields from TastingNote
    tasting_fields = set(TastingNote.model_fields.keys())

    # Get all fields from TastingData
    data_fields = set(TastingData.model_fields.keys())

    # Should have same fields (or document differences)
    missing_from_data = tasting_fields - data_fields
    extra_in_data = data_fields - tasting_fields

    assert len(missing_from_data) == 0, f"TastingData missing: {missing_from_data}"
    # Known differences are OK if documented

def test_wine_fields_not_in_whiskey_templates():
    """Ensure type-specific fields don't leak between types"""
    # Wine template should NOT reference whiskey fields
    wine_template = read_template("tasting_wine.md.jinja")
    assert "whiskey_nose" not in wine_template
    assert "whiskey_palate" not in wine_template

    # Wine template MUST have appearance_notes
    assert "appearance_notes" in wine_template

    # Whiskey template should NOT have appearance_notes
    whiskey_template = read_template("tasting_whiskey.md.jinja")
    assert "appearance_notes" not in whiskey_template

def test_generator_context_includes_all_model_fields():
    """Ensure generator._prepare_context() includes all TastingNote fields"""
    from reserve_automation.generators.tasting_generator import TastingGenerator

    wine_tasting = TastingNote(
        bottle_name="Test",
        taster_name="Tester",
        tasting_date=date.today(),
        beverage_type="wine",
        appearance_notes=["ruby"],
        nose_notes=["vanilla"],
        # ... all fields
    )

    context = generator._prepare_context(wine_tasting, mock_bottle_match)

    # Check all wine-specific fields are in context
    assert "appearance_notes" in context
    assert context["appearance_notes"] == ["ruby"]
```

#### B. BottleMetadata Field Coherence

**Test the #CLAUDE_REQ chain**:
```python
def test_bottle_metadata_field_coherence():
    """Verify BottleMetadata fields match across all integration points"""
    # Create bottle with all fields
    bottle = BottleMetadata(
        producer="Test",
        name="Wine",
        type="wine",
        year=2020,
        abv=13.5,
        price=50.0,
        purchase_source="Wine Shop",
        inventory=2
    )

    # Test 1: to_obsidian_dict() includes all fields
    obsidian_dict = bottle.to_obsidian_dict()
    assert "Vintage" in obsidian_dict  # year -> Vintage for wine
    assert obsidian_dict["Inventory"] == 2
    assert obsidian_dict["PurchaseSource"] == "Wine Shop"

    # Test 2: Vault reader can parse it back
    vault_reader = VaultReader(temp_vault)
    # Write bottle, read it back, compare

    # Test 3: Field name map in management.py includes all fields
    from reserve_automation.web.routes.management import field_name_map
    assert "inventory" in field_name_map
    assert field_name_map["inventory"] == "Inventory"
```

---

### Priority 3: Web Route Tests 🟠 HIGH

**Impact**: 3,985 LOC of API endpoints without contract validation

#### Missing Coverage

##### A. `/routes/tastings.py` (990 LOC)
**Untested endpoints**:
- `GET /api/v1/tastings/{extraction_id}` - Session state retrieval
- `PUT /api/v1/tastings/{extraction_id}/{index}` - Update tasting data
- `POST /api/v1/tastings/{extraction_id}/{index}/select` - Match selection
- `POST /api/v1/tastings/{extraction_id}/{index}/approve` - Save tasting
- `POST /api/v1/manual-tasting/*` - Manual tasting wizard (6+ endpoints)

**Test examples**:
```python
def test_get_tasting_session_requires_auth():
    """Ensure session endpoints require authentication"""
    response = client.get("/api/v1/tastings/test-id")
    assert response.status_code == 401

def test_update_tasting_validates_scores():
    """Ensure score validation catches out-of-range values"""
    # Setup session
    extraction_id = create_test_session()

    # Try to set invalid whiskey score (max is 3.0)
    response = client.put(
        f"/api/v1/tastings/{extraction_id}/0",
        json={"tasting_data": {"whiskey_nose": 5.0}}  # Invalid!
    )

    assert response.status_code == 422
    assert "whiskey_nose" in response.json()["detail"]

def test_manual_tasting_wizard_state_machine():
    """Test wizard step transitions"""
    # Start session
    response = client.post("/api/v1/manual-tasting/start",
                          json={"mode": "obsidian", "beverage_type": "wine"})

    # Can't skip to step 3 without completing step 1
    response = client.put("/api/v1/manual-tasting/session/step",
                         json={"step": "tasting_form", "data": {...}})
    assert response.status_code == 400
```

##### B. `/routes/events.py` (354 LOC)
Already has functional tests, but missing:
- Error handling tests
- Permission/authorization tests
- Concurrent modification tests

##### C. `/routes/management.py` (699 LOC)
- Bottle search pagination
- Field name mapping validation
- Vault path construction

##### D. `/routes/bottles.py` (1,493 LOC)
- Extraction workflow error cases
- File upload validation
- Session management

---

### Priority 4: Utility Module Tests 🟡 MEDIUM

**Impact**: Core infrastructure with complex logic

#### Missing Coverage

##### A. `utils/bottle_matcher.py` (~200 LOC)
**Critical functions**:
```python
def test_bottle_matcher_fuzzy_vs_strict():
    """Test fuzzy vs strict matching modes"""
    matcher = BottleMatcher(vault_path)

    # Fuzzy should match "Stagg" to "George T. Stagg"
    fuzzy = matcher.find_matches("Stagg", "whiskey", strict_substring=False)
    assert len(fuzzy) > 0

    # Strict should only match exact substring
    strict = matcher.find_matches("Stagg", "whiskey", strict_substring=True)
    assert all("stagg" in m.bottle.name.lower() for m in strict)

def test_bottle_matcher_cache_invalidation():
    """Test cache invalidation after adding bottles"""
    matcher = BottleMatcher(vault_path)

    # Initial search
    results1 = matcher.find_matches("New Bottle", "wine")
    assert len(results1) == 0

    # Add bottle to vault
    add_bottle_to_vault(name="New Bottle", type="wine")

    # Without invalidation, should still return 0
    results2 = matcher.find_matches("New Bottle", "wine")
    assert len(results2) == 0  # Cache still active

    # After invalidation, should find it
    matcher.invalidate_cache("wine")
    results3 = matcher.find_matches("New Bottle", "wine")
    assert len(results3) == 1
```

##### B. `utils/vault_reader.py` (~300 LOC)
**Critical functions**:
```python
def test_vault_reader_parses_all_field_types():
    """Test parsing different frontmatter field types"""
    # Create test bottle file with various field formats
    bottle_content = '''---
fileClass: Wine
Name: "Test Wine"
Winemaker: Producer Name
Vintage: "2020"
ABV: 13.5
Price: 45.99
Inventory: 2
---
'''

    bottle = vault_reader._parse_bottle_file(test_file, "wine", test_dir)

    assert bottle.producer == "Producer Name"
    assert bottle.year == 2020
    assert bottle.abv == 13.5
    assert bottle.inventory == 2

def test_vault_reader_handles_malformed_frontmatter():
    """Test error handling for malformed files"""
    malformed = '''---
Invalid YAML: [unclosed
---'''

    bottle = vault_reader._parse_bottle_file(test_file, "wine", test_dir)
    assert bottle is None  # Should return None, not crash
```

##### C. `utils/obsidian_updater.py`
- Template synchronization
- Frontmatter updates
- Backup/restore logic

---

## 3. Test Pyramid Rebalancing

### Current Pyramid (Inverted ⚠️)
```
        /\
       /  \  Functional Tests (High)
      /____\
     /      \  Integration Tests (Medium)
    /        \
   /          \ Unit Tests (LOW - 81 tests)
  /______________\
```

### Target Pyramid
```
        /\
       /  \  E2E Tests (10-15 tests)
      /____\
     /      \  Integration Tests (30-40 tests)
    /        \
   /          \ Unit Tests (HIGH - 200+ tests)
  /______________\
```

### Recommended Split

#### Unit Tests (200+ tests total)
- Service layer: ~80 tests (20 per service)
- Model validation: ~30 tests (coherence, conversion, serialization)
- Utilities: ~40 tests (bottle matching, vault reading, duplicate detection)
- Keep existing: 81 tests (extractors, parsers, generators, LLM)

#### Integration Tests (30-40 tests)
- Service + vault interactions: ~15 tests
- API endpoint contracts: ~15 tests
- Template rendering pipeline: ~10 tests

#### E2E Tests (10-15 tests)
- Keep existing functional tests but reduce overlap
- Focus on critical user journeys
- Event workflows, extraction workflows, manual entry

---

## 4. Test Infrastructure Improvements

### A. Test Fixtures & Helpers
**Create shared fixtures**:
```python
# tests/conftest.py
@pytest.fixture
def temp_vault(tmp_path):
    """Create temporary vault with sample bottles"""
    vault = tmp_path / "vault"
    vault.mkdir()

    # Create wine bottles
    create_sample_wine(vault, "Caymus - Cabernet - 2019")
    create_sample_wine(vault, "Chateau - Merlot - 2020")

    # Create whiskey bottles
    create_sample_whiskey(vault, "Buffalo Trace - Bourbon")
    create_sample_whiskey(vault, "Stagg - Bourbon - 2022")

    return vault

@pytest.fixture
def mock_llm_service():
    """Mock LLM service with canned responses"""
    service = Mock()
    service.complete = AsyncMock(return_value=LLMResponse(...))
    return service

@pytest.fixture
def sample_tastings():
    """Create sample tasting notes for all beverage types"""
    return {
        "wine": create_wine_tasting(),
        "whiskey": create_whiskey_tasting()
    }
```

### B. Test Data Builders
```python
# tests/builders.py
class TastingNoteBuilder:
    """Builder pattern for creating test TastingNote objects"""

    def __init__(self):
        self._data = {
            "bottle_name": "Test Bottle",
            "taster_name": "Test Taster",
            "tasting_date": date.today(),
            "beverage_type": "wine"
        }

    def wine(self):
        self._data["beverage_type"] = "wine"
        return self

    def with_scores(self, appearance=2.5, aroma=5.0, taste=5.0, aftertaste=2.5, overall=1.5):
        self._data.update({
            "wine_appearance": appearance,
            "wine_aroma": aroma,
            # ...
        })
        return self

    def build(self):
        return TastingNote(**self._data)

# Usage:
tasting = TastingNoteBuilder().wine().with_scores().build()
```

### C. Contract Testing
```python
# tests/contracts/test_api_contracts.py
def test_tasting_session_response_schema():
    """Ensure API response matches documented schema"""
    response = client.get(f"/api/v1/tastings/{extraction_id}")
    data = response.json()

    # Validate against Pydantic schema
    TastingSessionResponse(**data)  # Should not raise

def test_error_response_format():
    """Ensure all error responses follow consistent format"""
    # All 4xx/5xx should return: {"detail": "message", "code": "ERROR_CODE"}
```

### D. Property-Based Testing
```python
# Use Hypothesis for edge cases
from hypothesis import given, strategies as st

@given(
    producer=st.text(min_size=1, max_size=200),
    name=st.text(min_size=1, max_size=200),
    year=st.integers(min_value=1800, max_value=2030)
)
def test_bottle_metadata_valid_for_any_input(producer, name, year):
    """Test BottleMetadata accepts any valid input"""
    bottle = BottleMetadata(
        producer=producer,
        name=name,
        year=year,
        type="wine",
        source="test"
    )

    # Should successfully create and serialize
    bottle.model_dump()
```

---

## 5. Example Test Cases for Top 5 Gaps

### Gap 1: Tasting Service - Session Creation
```python
# tests/unit/services/test_tasting_service.py

def test_create_session_sets_correct_status():
    """Test that high-confidence matches are auto-selected"""
    service = TastingService(core_config)

    # Mock high-confidence match (>= 0.8)
    with patch.object(service, 'get_match_candidates') as mock_match:
        mock_match.return_value = [
            MatchCandidate(bottle_path="1_Whiskeys/Stagg", confidence=0.95, ...)
        ]

        extraction = TastingExtractionResult(
            tastings=[create_whiskey_tasting()],
            template_type="bourbon"
        )

        session = service.create_session_from_extraction("id1", extraction)

        # Should auto-select high confidence match
        assert session.tastings[0].status == TastingStatus.MATCHED
        assert session.tastings[0].selected_match == "1_Whiskeys/Stagg"

def test_create_session_detects_count_mismatch():
    """Test count mismatch detection"""
    service = TastingService(core_config)

    extraction = TastingExtractionResult(
        tastings=[create_whiskey_tasting(), create_whiskey_tasting()],
        template_type="bourbon"
    )

    session = service.create_session_from_extraction(
        "id1",
        extraction,
        expected_count=3  # User expected 3, but only got 2
    )

    assert session.count_mismatch is True
    assert session.expected_count == 3
    assert session.actual_count == 2
```

### Gap 2: Model Coherence - Field Completeness
```python
# tests/unit/models/test_schema_coherence.py

def test_tasting_data_has_all_tasting_note_fields():
    """Ensure TastingData schema matches TastingNote"""
    from reserve_automation.core.tasting_note import TastingNote
    from reserve_automation.web.schemas.tasting import TastingData

    # Fields that should be in both
    common_fields = {
        "bottle_name", "taster_name", "tasting_date", "beverage_type",
        "wine_appearance", "wine_aroma", "wine_taste", "wine_aftertaste", "wine_overall",
        "whiskey_nose", "whiskey_palate", "whiskey_finish", "whiskey_overall",
        "appearance_notes", "nose_notes", "palate_notes", "finish_notes", "overall_notes",
        "days_from_crack", "fill_level"
    }

    tasting_note_fields = set(TastingNote.model_fields.keys())
    tasting_data_fields = set(TastingData.model_fields.keys())

    for field in common_fields:
        assert field in tasting_note_fields, f"TastingNote missing {field}"
        assert field in tasting_data_fields, f"TastingData missing {field}"

def test_bottle_metadata_field_name_map_complete():
    """Ensure field_name_map includes all BottleMetadata fields"""
    from reserve_automation.core.models import BottleMetadata
    from reserve_automation.web.routes.management import field_name_map

    # All user-facing fields should have Obsidian mapping
    mappable_fields = {
        "producer", "name", "year", "beverage_type", "country", "region",
        "variety", "vineyard", "age_statement", "proof", "mash_bill", "barrel_type",
        "abv", "price", "purchase_source", "inventory"
    }

    for field in mappable_fields:
        assert field in field_name_map, f"field_name_map missing {field}"
```

### Gap 3: Web Routes - Session Management
```python
# tests/integration/routes/test_tasting_routes.py

def test_session_persistence_across_requests():
    """Test that session data persists across API calls"""
    # Create session
    response = client.post("/api/v1/upload-tastings",
                          files={"file": test_image})
    extraction_id = response.json()["extraction_id"]

    # Get session (first request)
    response1 = client.get(f"/api/v1/tastings/{extraction_id}")
    session1 = response1.json()

    # Update tasting
    client.put(f"/api/v1/tastings/{extraction_id}/0",
              json={"tasting_data": {"whiskey_nose": 2.5}})

    # Get session again (second request)
    response2 = client.get(f"/api/v1/tastings/{extraction_id}")
    session2 = response2.json()

    # Changes should persist
    assert session2["tastings"][0]["tasting_data"]["whiskey_nose"] == 2.5

def test_session_isolation_between_users():
    """Test that users can't access each other's sessions"""
    # User 1 creates session
    session1 = requests.Session()
    response1 = session1.post("/api/v1/upload-tastings", files={"file": test_image})
    extraction_id = response1.json()["extraction_id"]

    # User 2 tries to access User 1's session
    session2 = requests.Session()
    response2 = session2.get(f"/api/v1/tastings/{extraction_id}")

    assert response2.status_code == 401  # Unauthorized
```

### Gap 4: Duplicate Detection - Edge Cases
```python
# tests/unit/services/test_duplicate_detection.py

def test_duplicate_detection_handles_unicode():
    """Test matching with unicode characters in names"""
    service = DuplicateDetectionService(vault_path)

    bottle = BottleMetadata(
        producer="Château Margaux",  # Unicode 'â'
        name="Pavillon Rouge",
        year=2015,
        type="wine",
        source="test"
    )

    # Should match existing "Chateau Margaux" (no unicode)
    duplicates = service.find_potential_duplicates(bottle, threshold=0.7)

    assert len(duplicates) > 0
    assert any("Margaux" in d["filename"] for d in duplicates)

def test_duplicate_detection_year_missing_vs_present():
    """Test matching when one bottle has year, other doesn't"""
    service = DuplicateDetectionService(vault_path)

    # Bottle with year
    bottle_with_year = BottleMetadata(
        producer="Buffalo Trace",
        name="Bourbon",
        year=2022,
        type="whiskey",
        source="test"
    )

    # Should still match "Buffalo Trace - Bourbon.md" (no year)
    # but with slightly lower confidence
    duplicates = service.find_potential_duplicates(bottle_with_year, threshold=0.5)

    no_year_match = [d for d in duplicates if "2022" not in d["filename"]]
    assert len(no_year_match) > 0
    assert no_year_match[0]["confidence"] >= 0.6
```

### Gap 5: Bottle Matcher - Cache & Fuzzy Logic
```python
# tests/unit/utils/test_bottle_matcher.py

def test_bottle_matcher_fuzzy_matching_typos():
    """Test fuzzy matching handles typos"""
    matcher = BottleMatcher(vault_path)

    # Typo: "Caymus" instead of "Caymus"
    matches = matcher.find_matches("Caymus Cabernet", "wine", min_score=0.5)

    # Should still find "Caymus - Cabernet Sauvignon - 2019"
    assert len(matches) > 0
    assert matches[0].bottle.producer == "Caymus"

def test_bottle_matcher_vault_path_in_results():
    """Test that matches include correct vault_path"""
    matcher = BottleMatcher(vault_path)

    matches = matcher.find_matches("Stagg", "whiskey")

    for match in matches:
        # vault_path should be set from vault_reader
        assert match.bottle.vault_path is not None
        assert match.bottle.vault_path.startswith("1_Whiskeys/")

def test_bottle_matcher_event_mode_filtering():
    """Test event bottle filtering in tasting_service"""
    # This is actually in tasting_service, but critical for bottle matching
    service = TastingService(core_config)

    # Create event with 2 bottles
    event_id = "test-event"
    event_store[event_id] = {
        "bottles": [
            {"bottle_path": "1_Whiskeys/Stagg", "bottle_name": "Stagg"},
            {"bottle_path": "1_Whiskeys/EH-Taylor", "bottle_name": "EH Taylor"}
        ],
        "is_blind": False,
        "status": "open"
    }

    # Search should only return event bottles
    results = service.get_match_candidates(
        bottle_name="Buffalo Trace",  # NOT in event
        beverage_type="whiskey",
        event_id=event_id
    )

    assert len(results) == 0  # Should not find non-event bottle
```

---

## 6. Implementation Roadmap

### Phase 1: Critical Service Tests (Week 1)
**Goal**: Cover tasting_service.py and duplicate_service.py

1. Create `tests/unit/services/` directory
2. Write `test_tasting_service.py` (20 tests minimum)
   - Session creation (5 tests)
   - Match candidates (5 tests)
   - Duplicate detection (3 tests)
   - Save operations (5 tests)
   - Data conversions (2 tests)
3. Write `test_duplicate_service.py` (15 tests)
   - Similarity calculations (8 tests)
   - Edge cases (7 tests)

**Success Metric**: 35 new unit tests, service test coverage > 80%

### Phase 2: Model Coherence Tests (Week 2)
**Goal**: Prevent field-sync bugs like appearance_notes

1. Create `tests/unit/models/` directory
2. Write `test_schema_coherence.py` (10 tests)
   - Field completeness checks (3 tests)
   - Conversion round-trips (3 tests)
   - Type validation (4 tests)
3. Write `test_bottle_metadata.py` (10 tests)
   - Obsidian dict conversion (5 tests)
   - Field name mapping (5 tests)

**Success Metric**: 20 new tests, automated coherence checks

### Phase 3: Web Route Contract Tests (Week 3)
**Goal**: API stability and error handling

1. Create `tests/integration/routes/` directory
2. Write `test_tasting_routes.py` (15 tests)
   - Session management (5 tests)
   - Data updates (5 tests)
   - Error cases (5 tests)
3. Write `test_event_routes.py` (10 tests)
   - Event creation/joining (5 tests)
   - Permissions (3 tests)
   - Concurrent access (2 tests)

**Success Metric**: 25 new integration tests, all API endpoints tested

### Phase 4: Utility Module Tests (Week 4)
**Goal**: Infrastructure reliability

1. Write `test_bottle_matcher.py` (20 tests)
2. Write `test_vault_reader.py` (15 tests)
3. Write `test_obsidian_updater.py` (10 tests)

**Success Metric**: 45 new tests, utility coverage > 85%

### Phase 5: CI Integration (Week 5)
**Goal**: Automated testing

1. Set up GitHub Actions / CI pipeline
2. Configure test stages (unit → integration → E2E)
3. Add coverage reporting (target: 80% overall)
4. Make tests required for PR merges

**Success Metric**: All PRs automatically tested, coverage visible

---

## 7. Test Naming Conventions

### Recommended Pattern
```python
# Format: test_<function>_<scenario>_<expected_outcome>

# Good:
def test_create_session_high_confidence_match_auto_selected()
def test_duplicate_detection_unicode_names_matched()
def test_bottle_matcher_cache_invalidated_after_add()

# Bad:
def test_session()  # Too vague
def test_1()  # Not descriptive
def test_creates_session_from_extraction()  # Missing scenario/outcome
```

### Test Organization
```
tests/
├── unit/                       # Pure unit tests (no external dependencies)
│   ├── services/
│   │   ├── test_tasting_service.py
│   │   ├── test_duplicate_service.py
│   │   └── test_extraction_service.py
│   ├── models/
│   │   ├── test_schema_coherence.py
│   │   └── test_bottle_metadata.py
│   ├── utils/
│   │   ├── test_bottle_matcher.py
│   │   └── test_vault_reader.py
│   └── (existing)
│       ├── test_extractors.py
│       ├── test_generators.py
│       ├── test_llm_gateway.py
│       └── test_parsers.py
├── integration/                # Component integration (DB, vault, services)
│   ├── routes/
│   │   ├── test_tasting_routes.py
│   │   ├── test_event_routes.py
│   │   └── test_management_routes.py
│   ├── test_vault_operations.py
│   └── (existing)
│       ├── test_bottle_extraction_cli.py
│       └── test_bottle_extraction_web.py
├── functional/                 # E2E user workflows
│   ├── events/
│   │   ├── test_edit_tasting.py
│   │   └── test_multi_event.py
│   └── tastings/
│       ├── test_event_tastings.py
│       ├── test_cli_extraction.py
│       └── test_vault_integration.py
└── conftest.py                # Shared fixtures
```

---

## 8. Monitoring & Maintenance

### Coverage Goals
- **Unit tests**: 85%+ coverage of service/model/util modules
- **Integration tests**: 70%+ coverage of routes/API endpoints
- **Overall**: 80%+ code coverage

### Regression Prevention
```python
# Add this test whenever a bug is fixed
def test_regression_appearance_notes_field():
    """
    Regression test for appearance_notes field bug.

    Bug: appearance_notes was missing from TastingData schema, causing
    wine tastings to lose appearance notes during session conversion.

    Fixed: 2025-12-XX
    """
    tasting = TastingNote(
        beverage_type="wine",
        appearance_notes=["ruby", "clear"],
        # ... other fields
    )

    data = service._tasting_note_to_data(tasting)
    assert data.appearance_notes == ["ruby", "clear"]
```

### Test Review Checklist
When adding new features:
- [ ] Added unit tests for new functions
- [ ] Updated integration tests if API contracts changed
- [ ] Verified schema coherence across components
- [ ] Checked field name mappings if models changed
- [ ] Added regression test if fixing a bug
- [ ] Updated test documentation

---

## Summary

### Test Count Targets
| Current | Target | Gap |
|---------|--------|-----|
| 81 unit tests | 200+ unit tests | **+119 tests needed** |
| 2 integration modules | 6 integration modules | **+4 modules needed** |
| 7 functional suites | 5 focused E2E tests | **-2 (consolidate)** |

### Critical Gaps to Address (Priority Order)
1. **Service layer tests** (tasting_service, duplicate_service) - 35 tests
2. **Model coherence tests** (field sync, schema validation) - 20 tests
3. **Web route tests** (API contracts, error handling) - 25 tests
4. **Utility tests** (bottle_matcher, vault_reader) - 45 tests
5. **CI integration** (automated testing, coverage reporting)

### Expected Outcomes
- **Prevent regressions** like appearance_notes bug (schema coherence tests)
- **Catch type errors** like wine showing whiskey fields (validation tests)
- **Ensure API stability** (contract tests)
- **Increase confidence** in refactoring (high coverage)
- **Faster debugging** (failures pinpoint exact issue)

### Next Steps
1. **Week 1**: Implement service layer tests (Priority 1)
2. **Week 2**: Implement schema coherence tests (Priority 2)
3. **Week 3**: Implement API contract tests (Priority 3)
4. **Week 4**: Implement utility tests (Priority 4)
5. **Week 5**: Set up CI pipeline

---

**Report Generated**: 2025-12-27
**Analysis By**: Claude Code Testing Analysis
**Files Analyzed**: 24 test files, 70+ source files
**Total LOC Reviewed**: ~15,000 lines
