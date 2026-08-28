#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
import os, random, subprocess, sys, tempfile
from pathlib import Path
cli=Path(sys.argv[1]); rng=random.Random(0x50504335)
magics=[b'\x7fELF',b'\xfe\xed\xfa\xce',b'Joy!peff',b'\xca\xfe\xba\xbe']
with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    for i in range(120):
        n=rng.randrange(0,1025); data=bytearray(rng.randrange(256) for _ in range(n))
        magic=magics[i%len(magics)]
        if len(data)<len(magic): data.extend(b'\0'*(len(magic)-len(data)))
        data[:len(magic)]=magic
        p=td/f'case-{i}.bin';p.write_bytes(data)
        cp=subprocess.run([str(cli),'image-info',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=2)
        if cp.returncode not in (0,1): raise SystemExit(f'crash/abnormal exit {cp.returncode} on {i}')
print('malformed intake stress passed')
