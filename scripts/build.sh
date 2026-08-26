#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release -DPPC_LAB_ENABLE_UNICORN=ON
cmake --build build/release --parallel
printf '\nBuilt: %s\n' "$ROOT/build/release/ppc-lab"
