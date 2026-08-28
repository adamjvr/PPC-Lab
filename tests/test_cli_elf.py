#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def make_elf(path: Path) -> None:
    code_addr = 0x00100000
    code_off = 0x100
    data_addr = 0x00200000
    data_off = 0x108
    blob = bytearray(0x10C)
    blob[:7] = b"\x7fELF\x01\x02\x01"

    def w16(off: int, value: int) -> None:
        blob[off:off+2] = struct.pack(">H", value)

    def w32(off: int, value: int) -> None:
        blob[off:off+4] = struct.pack(">I", value)

    w16(16, 2)
    w16(18, 20)
    w32(20, 1)
    w32(24, code_addr)
    w32(28, 52)
    w16(40, 52)
    w16(42, 32)
    w16(44, 2)

    ph0 = 52
    for off, value in [
        (0, 1), (4, code_off), (8, code_addr), (12, code_addr),
        (16, 8), (20, 8), (24, 5), (28, 4),
    ]:
        w32(ph0 + off, value)

    ph1 = ph0 + 32
    for off, value in [
        (0, 1), (4, data_off), (8, data_addr), (12, data_addr),
        (16, 4), (20, 16), (24, 6), (28, 4),
    ]:
        w32(ph1 + off, value)

    w32(code_off + 0, 0x38630007)  # addi r3,r3,7
    w32(code_off + 4, 0x4E800020)  # blr
    w32(data_off, 0x11223344)
    path.write_bytes(blob)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, text=True, capture_output=True)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_cli_elf.py /path/to/ppc-lab", file=sys.stderr)
        return 2
    exe = sys.argv[1]
    with tempfile.TemporaryDirectory(prefix="ppc-lab-cli-") as td:
        elf = Path(td) / "fixture.elf"
        make_elf(elf)

        info = run(exe, "elf-info", str(elf))
        assert info.returncode == 0, info.stderr
        assert "machine=20 (EM_PPC)" in info.stdout
        assert "entry=0x00100000" in info.stdout
        assert "segments=2" in info.stdout

        metadata = run(exe, "metadata", str(elf))
        assert metadata.returncode == 0, metadata.stderr
        meta = json.loads(metadata.stdout)
        assert meta["schema"] == "ppc-lab-metadata-v1"
        assert meta["format"] == "ELF32-PPC-BE"
        assert meta["entry"] == "0x00100000"
        assert len(meta["regions"]) == 2

        dis = run(exe, "disasm", "--elf", str(elf), "--count", "2")
        assert dis.returncode == 0, dis.stderr
        assert "addi r3,r3,7" in dis.stdout
        assert "blr" in dis.stdout

        call = run(exe, "call", "--elf", str(elf), "--backend", "builtin", "--set", "r3=5")
        assert call.returncode == 0, call.stderr + call.stdout
        assert "stop=returned" in call.stdout
        assert "r03=0x0000000c" in call.stdout

        analyze = run(exe, "analyze", str(elf), "--json")
        assert analyze.returncode == 0, analyze.stderr
        analysis = json.loads(analyze.stdout)
        assert analysis["schema"] == "ppc-lab-analysis-v1"
        assert analysis["format"] == "ELF32-PPC-BE"

        auto_dis = run(exe, "disasm", "--image", str(elf), "--count", "2")
        assert auto_dis.returncode == 0, auto_dis.stderr
        assert "addi r3,r3,7" in auto_dis.stdout

        auto_call = run(exe, "run", "--image", str(elf), "--backend", "builtin", "--set", "r3=5")
        assert auto_call.returncode == 0, auto_call.stderr + auto_call.stdout
        assert "r03=0x0000000c" in auto_call.stdout

        caps = run(exe, "capabilities", "--json")
        assert caps.returncode == 0, caps.stderr
        cap = json.loads(caps.stdout)
        assert cap["schema"] == "ppc-lab-capabilities-v1"
        assert cap["guest"] == {"architecture": "ppc32", "endian": "big"}
        assert "ELF32-PPC-BE" in cap["formats"]

        doctor = run(exe, "doctor")
        assert doctor.returncode == 0, doctor.stderr + doctor.stdout
        assert "status=PASS" in doctor.stdout

        version = run(exe, "--version")
        assert version.returncode == 0
        assert version.stdout.strip() == "PPC Lab 1.0.0"

    print("PASS: ELF32 CLI inspect/disasm/call")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
