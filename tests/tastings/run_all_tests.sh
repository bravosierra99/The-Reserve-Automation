#!/bin/bash
# Master test runner for tasting upload system
#
# Run from project root: ./tests/tastings/run_all_tests.sh
# Or from tests/tastings: ./run_all_tests.sh

set -e  # Exit on error

BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory (works even if called from elsewhere)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     THE RESERVE - TASTING UPLOAD TEST SUITE              ║${NC}"
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo ""

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Function to run a test suite
run_test_suite() {
    local suite_name="$1"
    local test_script="$2"

    TESTS_RUN=$((TESTS_RUN + 1))

    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}SUITE $TESTS_RUN: $suite_name${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    if eval "$test_script"; then
        echo -e "${GREEN}✅ PASSED: $suite_name${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "${RED}❌ FAILED: $suite_name${NC}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

# Check if web server is running (needed for suites 1 and 3)
echo -e "${YELLOW}🔍 Checking if web server is running...${NC}"
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "${GREEN}   ✓ Web server is running${NC}"
else
    echo -e "${RED}   ❌ Web server is not running${NC}"
    echo ""
    echo "Please start the web server first:"
    echo "  ./start-web.sh"
    echo ""
    echo "For vault integration tests (Suite 3), restart with test vault:"
    echo "  RESERVE_VAULT_PATH=/tmp/test-vault ./start-web.sh"
    exit 1
fi

# Setup test vault
echo ""
echo -e "${YELLOW}🔧 Setting up test vault...${NC}"
mkdir -p /tmp/test-vault/1_Whiskeys /tmp/test-vault/1_Wines
echo -e "${GREEN}   ✓ Test vault ready at /tmp/test-vault${NC}"

# Suite 1: Event-Based Tastings (SAFE - No Vault Writes)
run_test_suite "Event-Based Tastings (No Vault Writes)" \
    "cd '$PROJECT_ROOT' && python3 tests/tastings/test_event_tastings.py" || true

# Suite 1b: Manual Tasting UI Tests (SAFE)
run_test_suite "Manual Tasting UI Tests (Form Fields)" \
    "cd '$PROJECT_ROOT' && python3 tests/tastings/test_manual_tasting_ui.py" || true

# Suite 2: CLI Extraction with --dry-run (SAFE)
run_test_suite "CLI Extraction Tests (Dry-Run)" \
    "cd '$PROJECT_ROOT' && python3 tests/tastings/test_cli_extraction.py" || true

# Suite 3: Vault Integration (Writes to /tmp/test-vault)
echo ""
echo -e "${YELLOW}⚠️  Suite 3 requires server restart with test vault${NC}"
read -p "Restart server with RESERVE_VAULT_PATH=/tmp/test-vault? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}   Please restart server manually:${NC}"
    echo "   pkill -f uvicorn"
    echo "   RESERVE_VAULT_PATH=/tmp/test-vault ./start-web.sh"
    echo ""
    read -p "Press Enter when server is restarted..." -r

    run_test_suite "Vault Integration (Temp Vault)" \
        "cd '$PROJECT_ROOT' && python3 tests/tastings/test_vault_integration.py" || true
else
    echo -e "${YELLOW}   Skipping Suite 3${NC}"
fi

# Summary
echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                      TEST SUMMARY                          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Total Suites:  ${TESTS_RUN}"
echo -e "  ${GREEN}Passed:        ${TESTS_PASSED}${NC}"
echo -e "  ${RED}Failed:        ${TESTS_FAILED}${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 ALL TASTING TESTS PASSED!${NC}"
    echo ""
    echo "Test Coverage:"
    echo "  ✓ Event-based tastings (in-memory, no vault writes)"
    echo "  ✓ CLI extraction with --dry-run"
    echo "  ✓ Vault integration (temp vault at /tmp/test-vault)"
    exit 0
else
    echo -e "${RED}⚠️  SOME TESTS FAILED${NC}"
    echo ""
    echo "Review the output above for details."
    exit 1
fi
