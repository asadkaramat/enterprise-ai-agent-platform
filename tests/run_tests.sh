#!/usr/bin/env bash
# Run the full E2E test suite against the live Docker Compose stack.
# Usage:
#   ./tests/run_tests.sh               # run all tests
#   ./tests/run_tests.sh -k health     # run only health tests
#   ./tests/run_tests.sh -x            # stop on first failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing test dependencies..."
pip install -q "$SCRIPT_DIR"

echo "==> Waiting for gateway to be ready..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "    Gateway is up."
    break
  fi
  echo "    Attempt $i/30 — retrying in 3s..."
  sleep 3
done

echo "==> Running E2E tests..."
cd "$SCRIPT_DIR"
pytest "$@"
