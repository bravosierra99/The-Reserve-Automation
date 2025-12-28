#!/bin/bash
# Master test runner for tasting automation event tests
#
# Run from project root: ./tests/events/run_all_tests.sh
# Or from tests/events: ./run_all_tests.sh

set -e  # Exit on error

BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory (works even if called from elsewhere)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     THE RESERVE AUTOMATION - EVENT TEST SUITE             ║${NC}"
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo ""

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Function to run a test
run_test() {
    local test_name="$1"
    local test_script="$2"

    TESTS_RUN=$((TESTS_RUN + 1))

    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}TEST $TESTS_RUN: $test_name${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    if eval "$test_script"; then
        echo -e "${GREEN}✅ PASSED: $test_name${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "${RED}❌ FAILED: $test_name${NC}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

# Cleanup before tests
echo -e "${YELLOW}🧹 Cleaning up previous test events...${NC}"
python3 "$SCRIPT_DIR/cleanup_test_events.py" || true
echo ""

# Test 1: Blind Whiskey Event
run_test "Blind Whiskey Event" "
    python3 '$SCRIPT_DIR/create_test_event.py' &&
    python3 '$SCRIPT_DIR/populate_event_tastings.py' > /dev/null
" || true

# Test 2: Blind Wine Event
run_test "Blind Wine Event" "
    python3 '$SCRIPT_DIR/create_wine_event.py' &&
    python3 '$SCRIPT_DIR/populate_wine_event.py' > /dev/null
" || true

# Test 3: Multi-Event Participation
run_test "Multi-Event Participation" "
    python3 '$SCRIPT_DIR/test_multi_event.py'
" || true

# Test 4: Edit Existing Tasting
run_test "Edit Existing Tasting" "
    python3 '$SCRIPT_DIR/test_edit_tasting.py'
" || true

# Summary
echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                      TEST SUMMARY                          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Total Tests:   ${TESTS_RUN}"
echo -e "  ${GREEN}Passed:        ${TESTS_PASSED}${NC}"
echo -e "  ${RED}Failed:        ${TESTS_FAILED}${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 ALL TESTS PASSED!${NC}"
    echo ""
    echo "Test events are still running. View them at:"
    echo "  http://localhost:8000/events"
    echo ""
    echo "To clean up test events, run:"
    echo "  python3 $SCRIPT_DIR/cleanup_test_events.py"
    exit 0
else
    echo -e "${RED}⚠️  SOME TESTS FAILED${NC}"
    echo ""
    echo "Review the output above for details."
    echo ""
    echo "To clean up test events anyway, run:"
    echo "  python3 $SCRIPT_DIR/cleanup_test_events.py"
    exit 1
fi
