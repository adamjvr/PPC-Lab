#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 scripts/check_repository_invariants.py
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release -DPPC_LAB_ENABLE_UNICORN=ON
cmake --build build/release --parallel
ctest --test-dir build/release --output-on-failure
./build/release/ppc-lab selftest --backend builtin
if command -v clang++ >/dev/null 2>&1; then
  cmake -S . -B build/sanitize -DCMAKE_BUILD_TYPE=Debug \
    -DCMAKE_CXX_COMPILER=clang++ -DPPC_LAB_ENABLE_UNICORN=OFF -DPPC_LAB_ENABLE_SANITIZERS=ON
  cmake --build build/sanitize --parallel
  ctest --test-dir build/sanitize --output-on-failure
fi
