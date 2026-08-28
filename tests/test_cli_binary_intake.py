#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only

import pathlib
import struct
import subprocess
import sys
import tempfile

BIN = pathlib.Path(sys.argv[1]).resolve()


def run(*args: str) -> str:
    p = subprocess.run([str(BIN), *map(str, args)], text=True, capture_output=True)
    if p.returncode != 0:
        raise AssertionError(f"command failed ({p.returncode}): {' '.join(map(str,args))}\nstdout:\n{p.stdout}\nstderr:\n{p.stderr}")
    return p.stdout


def be16(v: int) -> bytes:
    return struct.pack(">H", v)


def be32(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)


def put32(buf: bytearray, off: int, v: int) -> None:
    buf[off:off+4] = be32(v)


def put16(buf: bytearray, off: int, v: int) -> None:
    buf[off:off+2] = be16(v)


def put_name(buf: bytearray, off: int, s: str) -> None:
    raw = s.encode("ascii")[:16]
    buf[off:off+len(raw)] = raw


def make_macho(path: pathlib.Path) -> None:
    vm, fileoff = 0x00100000, 0x100
    seg_cmd, thread_cmd = 124, 20
    b = bytearray(0x108)
    put32(b, 0, 0xFEEDFACE)
    put32(b, 4, 18)          # CPU_TYPE_POWERPC
    put32(b, 8, 0)
    put32(b, 12, 2)          # MH_EXECUTE
    put32(b, 16, 2)
    put32(b, 20, seg_cmd + thread_cmd)
    put32(b, 24, 0)
    o = 28
    put32(b, o, 1)           # LC_SEGMENT
    put32(b, o + 4, seg_cmd)
    put_name(b, o + 8, "__TEXT")
    put32(b, o + 24, vm)
    put32(b, o + 28, 0x100)
    put32(b, o + 32, fileoff)
    put32(b, o + 36, 8)
    put32(b, o + 40, 5)
    put32(b, o + 44, 5)
    put32(b, o + 48, 1)
    put_name(b, o + 56, "__text")
    put_name(b, o + 72, "__TEXT")
    put32(b, o + 88, vm)
    put32(b, o + 92, 8)
    put32(b, o + 96, fileoff)
    put32(b, o + 100, 2)
    put32(b, o + 112, 0x80000400)
    o += seg_cmd
    put32(b, o, 5)           # LC_UNIXTHREAD
    put32(b, o + 4, thread_cmd)
    put32(b, o + 8, 1)
    put32(b, o + 12, 1)
    put32(b, o + 16, vm)     # synthetic minimal thread PC accepted by loader
    put32(b, fileoff, 0x38630007)   # addi r3,r3,7
    put32(b, fileoff + 4, 0x4E800020) # blr
    path.write_bytes(b)


def make_pef(path: pathlib.Path) -> None:
    code, data, loader = 0x80, 0x88, 0x8C
    loader_size = 70
    b = bytearray(loader + loader_size)
    put32(b, 0, 0x4A6F7921)  # Joy!
    put32(b, 4, 0x70656666)  # peff
    put32(b, 8, 0x70777063)  # pwpc
    put32(b, 12, 1)
    put16(b, 32, 3)
    put16(b, 34, 2)

    def section(i: int, total: int, unpacked: int, packed: int, off: int, kind: int, align: int) -> None:
        o = 40 + i * 28
        put32(b, o + 8, total)
        put32(b, o + 12, unpacked)
        put32(b, o + 16, packed)
        put32(b, o + 20, off)
        b[o + 24] = kind
        b[o + 26] = align

    section(0, 8, 8, 8, code, 0, 2)
    section(1, 4, 4, 4, data, 1, 2)
    section(2, 0, 0, loader_size, loader, 4, 0)
    put32(b, code, 0x38630007)
    put32(b, code + 4, 0x4E800020)
    put32(b, data, 0)
    put32(b, loader + 0, 0)           # main section
    put32(b, loader + 4, 0)           # main offset
    put32(b, loader + 8, 0xFFFFFFFF)  # init absent
    put32(b, loader + 16, 0xFFFFFFFF) # term absent
    put32(b, loader + 32, 1)          # relocation section count
    put32(b, loader + 36, 68)         # relocation instr offset
    put32(b, loader + 40, 70)
    put32(b, loader + 44, 70)
    put16(b, loader + 56, 1)          # target section = data
    put32(b, loader + 60, 1)          # one relocation chunk
    put32(b, loader + 64, 0)
    put16(b, loader + 68, 0x6600)     # RelocSmBySection section 0
    path.write_bytes(b)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ppclab-cli-intake-") as td:
        root = pathlib.Path(td)
        macho = root / "fixture.macho"
        pef = root / "fixture.pef"
        make_macho(macho)
        make_pef(pef)

        out = run("image-info", macho)
        assert "format=mach-o-ppc32-be" in out.lower()
        assert "entry=0x00100000" in out.lower()
        out = run("macho-info", macho)
        assert "type=2 (MH_EXECUTE)" in out
        out = run("disasm", "--macho", macho, "--count", "2")
        assert "addi r3,r3,7" in out
        assert "blr" in out
        out = run("call", "--macho", macho, "--backend", "builtin", "--set", "r3=5")
        assert "stop=returned" in out.lower()
        assert "r03=0x0000000c" in out.lower()
        out = run("run", "--image", macho, "--backend", "builtin", "--set", "r3=5")
        assert "r03=0x0000000c" in out.lower()
        out = run("analyze", macho)
        assert "format=Mach-O-PPC32-BE" in out

        out = run("image-info", pef)
        assert "format=pef-cfm-ppc" in out.lower()
        assert "main=0:0x00000000" in out.lower()
        out = run("pef-info", pef)
        assert "architecture=pwpc" in out.lower()
        out = run("disasm", "--pef", pef, "--image-base", "0x11000000", "--count", "2")
        assert "addi r3,r3,7" in out
        assert "blr" in out
        out = run("call", "--pef", pef, "--image-base", "0x11000000", "--backend", "builtin", "--set", "r3=5")
        assert "stop=returned" in out.lower()
        assert "r03=0x0000000c" in out.lower()
        out = run("run", "--image", pef, "--image-base", "0x11000000", "--backend", "builtin", "--set", "r3=5")
        assert "r03=0x0000000c" in out.lower()
        out = run("analyze", pef)
        assert "format=PEF-CFM-PPC" in out

    print("PPC Lab binary-intake CLI tests passed")


if __name__ == "__main__":
    main()
