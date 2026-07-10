#!/usr/bin/env bash
# Run all integration tests against localhost:8000
# Usage: bash scripts/run_all_tests.sh

set -e

echo "=========================================="
echo "  Oneiros API — Integration Test Suite"
echo "=========================================="
echo ""

# Check if server is running
if ! curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "❌ Server is not running on http://localhost:8000"
    echo "   Start it with: cd oneiros-api && poetry run uvicorn app.main:app --reload"
    exit 1
fi

echo "✅ Server is running"
echo ""

# Run each test script
SCRIPTS_DIR="$(dirname "$0")"

echo "──────────────────────────────────────────"
echo "  1. Health Check"
echo "──────────────────────────────────────────"
python "$SCRIPTS_DIR/test_health.py"

echo "──────────────────────────────────────────"
echo "  2. Client Registration"
echo "──────────────────────────────────────────"
python "$SCRIPTS_DIR/test_clients.py"

echo "──────────────────────────────────────────"
echo "  3. Dream CRUD"
echo "──────────────────────────────────────────"
python "$SCRIPTS_DIR/test_dreams.py"

echo "──────────────────────────────────────────"
echo "  4. Dialogue"
echo "──────────────────────────────────────────"
python "$SCRIPTS_DIR/test_dialogue.py"

echo "──────────────────────────────────────────"
echo "  5. Analysis"
echo "──────────────────────────────────────────"
python "$SCRIPTS_DIR/test_analysis.py"

echo "──────────────────────────────────────────"
echo "  6. Sync (Backup/Restore)"
echo "──────────────────────────────────────────"
python "$SCRIPTS_DIR/test_sync.py"

echo "──────────────────────────────────────────"
echo "  7. Image Generation"
echo "──────────────────────────────────────────"
python "$SCRIPTS_DIR/test_image.py"

echo ""
echo "=========================================="
echo "  ✅ All integration tests completed!"
echo "=========================================="
