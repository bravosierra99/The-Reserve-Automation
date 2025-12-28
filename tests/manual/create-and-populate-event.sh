#!/bin/bash
# Create a test event and populate it with tastings from 3 participants

set -e

echo "🎯 Creating and Populating Test Event"
echo "========================================"
echo ""

# Step 1: Create the event
echo "Step 1: Creating event..."
python3 /tmp/create_test_event.py
echo ""

# Step 2: Populate with tastings
echo "Step 2: Populating with tastings..."
python3 /tmp/populate_event_tastings.py
