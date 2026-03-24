#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# --- src/treeloom/ package tree ---
mkdir -p \
  "$ROOT/src/treeloom/model" \
  "$ROOT/src/treeloom/graph" \
  "$ROOT/src/treeloom/analysis" \
  "$ROOT/src/treeloom/query" \
  "$ROOT/src/treeloom/lang/builtin" \
  "$ROOT/src/treeloom/export" \
  "$ROOT/src/treeloom/overlay"

# --- tests/ tree ---
mkdir -p \
  "$ROOT/tests/model" \
  "$ROOT/tests/graph" \
  "$ROOT/tests/analysis" \
  "$ROOT/tests/query" \
  "$ROOT/tests/lang" \
  "$ROOT/tests/export" \
  "$ROOT/tests/fixtures/python" \
  "$ROOT/tests/fixtures/javascript" \
  "$ROOT/tests/fixtures/go" \
  "$ROOT/tests/fixtures/java" \
  "$ROOT/tests/fixtures/c" \
  "$ROOT/tests/fixtures/cpp" \
  "$ROOT/tests/fixtures/rust"

# --- scripts/ ---
mkdir -p "$ROOT/scripts"

echo "Scaffold complete: $ROOT"
