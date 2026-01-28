#!/bin/bash
# Run E2E tests with good defaults for visibility and timeout handling
#
# Usage:
#   ./run_e2e_tests.sh                    # Run all E2E tests
#   ./run_e2e_tests.sh test_name          # Run specific test
#   ./run_e2e_tests.sh -k "crop"          # Run tests matching pattern
#   ./run_e2e_tests.sh --fast             # Skip slow tests (LLM-dependent)
#   ./run_e2e_tests.sh --list             # Just list tests, don't run

set -e

cd "$(dirname "$0")/../.."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  E2E Test Runner${NC}"
echo -e "${BLUE}========================================${NC}"

# Parse arguments
FAST_MODE=false
LIST_ONLY=false
EXTRA_ARGS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --fast)
            FAST_MODE=true
            shift
            ;;
        --list)
            LIST_ONLY=true
            shift
            ;;
        *)
            EXTRA_ARGS="$EXTRA_ARGS $1"
            shift
            ;;
    esac
done

# Build pytest command
CMD="uv run pytest tests/e2e/"

# Add verbosity and live output
CMD="$CMD -v -s"

# Show short traceback for failures
CMD="$CMD --tb=short"

# Skip slow tests if requested
if [ "$FAST_MODE" = true ]; then
    echo -e "${YELLOW}Fast mode: Skipping slow tests (LLM-dependent)${NC}"
    CMD="$CMD -m 'not slow'"
fi

# List tests only
if [ "$LIST_ONLY" = true ]; then
    echo -e "${BLUE}Collecting tests...${NC}"
    $CMD --collect-only -q $EXTRA_ARGS
    exit 0
fi

# Add any extra arguments
CMD="$CMD $EXTRA_ARGS"

echo -e "${GREEN}Running: $CMD${NC}"
echo ""

# Run tests
$CMD

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  E2E Tests Complete${NC}"
echo -e "${GREEN}========================================${NC}"
