#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"

inspect = subprocess.run(
    [sys.executable, str(ROOT / "scripts" / "ppc_result_inspect.py"),
     "--result", str(FIX / "import_result.json"), "--layout", str(FIX / "import_layout.json")],
    text=True, capture_output=True, check=True,
)
assert "import_index=3" in inspect.stdout
assert "import_name=cos" in inspect.stdout

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    values = [1.0, -2.5, 3.75]
    ppc_bytes = b"".join(struct.pack(">f", v) for v in values)
    ref = tmp / "native.raw"
    ref.write_bytes(b"".join(struct.pack("<f", v) for v in values))
    result = tmp / "ppc.json"
    result.write_text(json.dumps({
        "schema":"ppc-lab-result-v1",
        "dumps":[{"address":"0x40000000","size":len(ppc_bytes),"hex":ppc_bytes.hex(" ")}]
    }))
    compare = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "compare_ppc_dump.py"),
         "--ppc", str(result), "--reference", str(ref), "--mode", "float32",
         "--reference-endian", "le"], text=True, capture_output=True, check=True,
    )
    report = json.loads(compare.stdout)
    assert report["exact_float32_bits"] is True
    assert report["rms_error"] == 0.0

print("PPC result-tool tests passed")
