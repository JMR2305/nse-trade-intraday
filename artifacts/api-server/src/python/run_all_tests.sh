#!/usr/bin/env bash
# run_all_tests.sh — Unified Python test runner for ApexQuant AI.
#
# Runs every test_*.py file as an independent subprocess via uv.
# Aggregates exit codes and produces a final PASS/FAIL summary.
#
# Usage:
#   bash run_all_tests.sh          # run all test files
#   bash run_all_tests.sh -v       # verbose (show all output)
#   bash run_all_tests.sh -f       # stop on first failure
#
# Returns exit code 0 if all tests pass, 1 if any fail.
# PAPER TRADING / RESEARCH ONLY.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERBOSE=0
FAIL_FAST=0

while [[ $# -gt 0 ]]; do
  case $1 in
    -v|--verbose) VERBOSE=1; shift;;
    -f|--fail-fast) FAIL_FAST=1; shift;;
    *) echo "Unknown option: $1"; exit 1;;
  esac
done

PASS=0
FAIL=0
SKIP=0
declare -a FAILED_TESTS=()

cd "$SCRIPT_DIR"

TEST_FILES=$(ls test_*.py 2>/dev/null | sort)

if [[ -z "$TEST_FILES" ]]; then
  echo "No test_*.py files found in $SCRIPT_DIR"
  exit 1
fi

echo ""
echo "========================================================"
echo "  ApexQuant AI — Python Test Suite"
echo "  PAPER TRADING / RESEARCH ONLY"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================"
echo ""

for TEST_FILE in $TEST_FILES; do
  LABEL="$(printf '%-45s' "$TEST_FILE")"
  OUTPUT=$(uv run python "$TEST_FILE" 2>&1) || true
  EXIT_CODE=$?

  # Determine pass/fail
  HAS_FAIL=$(echo "$OUTPUT" | grep -iE "^[[:space:]]*(FAIL|FAILURES \()" | wc -l || true)
  HAS_ERROR=$(echo "$OUTPUT" | grep -iE "^(ERROR|Traceback|ImportError|ModuleNotFoundError)" | wc -l || true)
  LAST_LINE=$(echo "$OUTPUT" | tail -1)

  if [[ $EXIT_CODE -eq 0 && $HAS_FAIL -eq 0 && $HAS_ERROR -eq 0 ]]; then
    STATUS="PASS"
    PASS=$((PASS + 1))
    echo "  ✅  $LABEL  $STATUS"
  else
    STATUS="FAIL"
    FAIL=$((FAIL + 1))
    FAILED_TESTS+=("$TEST_FILE")
    echo "  ❌  $LABEL  $STATUS  (exit=$EXIT_CODE)"
    if [[ $VERBOSE -eq 1 ]]; then
      echo "$OUTPUT" | tail -20 | sed 's/^/      /'
    else
      echo "      $LAST_LINE"
    fi
    if [[ $FAIL_FAST -eq 1 ]]; then
      echo ""
      echo "  Stopping on first failure (--fail-fast)"
      break
    fi
  fi
done

TOTAL=$((PASS + FAIL + SKIP))
echo ""
echo "========================================================"
echo "  Results: $PASS passed, $FAIL failed, $SKIP skipped  (of $TOTAL)"
if [[ ${#FAILED_TESTS[@]} -gt 0 ]]; then
  echo ""
  echo "  Failed tests:"
  for f in "${FAILED_TESTS[@]}"; do
    echo "    • $f"
  done
fi
echo "========================================================"
echo ""

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
