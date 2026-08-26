# PPC Lab quick start

This is the shortest path from a fresh clone to a useful PowerPC research
result.

## 1. Requirements

Required:

- CMake 3.20 or newer;
- a C++20 compiler;
- Git if building from a clone.

Useful but optional:

- Python 3 for result-comparison and CLI integration tests;
- Clang for ASan/UBSan verification;
- Unicorn 2.x development files for the optional Unicorn backend.

PPC Lab always includes its own dependency-free PPC32 big-endian interpreter
and dependency-free ELF32 PowerPC loader.

## 2. Clone and verify

```bash
git clone https://github.com/YOUR-ACCOUNT/PPC-Lab.git
cd PPC-Lab
./Tools/verify.command
```

Expected end state: CMake configures, `ppc-lab` builds, CTest passes, built-in
PPC microtests pass, and sanitizer verification runs when suitable Clang is
installed.

## 3. Confirm the execution backend

```bash
./build/release/ppc-lab selftest --backend builtin
```

Use `--backend auto` to prefer Unicorn when PPC support is available, otherwise
fall back to the built-in interpreter.

## 4. Start with an ELF executable when you have one

Inspect it before running anything:

```bash
./build/release/ppc-lab elf-info ./firmware.elf
```

PPC Lab v0.2.0 accepts fixed-address ELF32, big-endian, `EM_PPC`, `ET_EXEC`
images. It maps `PT_LOAD` segments and zero-fills BSS.

Look at the entry-point instructions:

```bash
./build/release/ppc-lab disasm \
  --elf ./firmware.elf \
  --count 32
```

Execute from the ELF entry point:

```bash
./build/release/ppc-lab call \
  --elf ./firmware.elf \
  --backend builtin \
  --max-instructions 100000
```

For reverse engineering, it is often more useful to call one known function
than to pretend PPC Lab is the original operating system:

```bash
./build/release/ppc-lab call \
  --elf ./firmware.elf \
  --entry 0x00104560 \
  --set r3=0x40010000 \
  --set r4=64
```

See `docs/ELF32.md` for the exact loader contract and unsupported cases.

## 5. Raw/relocated code still works

PPC Lab maps raw binary bytes at deterministic addresses. The default raw code
base is `0x10000000`.

```bash
./build/release/ppc-lab call \
  --code ./code.bin \
  --entry 0x10000000 \
  --max-instructions 100000
```

You can inspect raw code too:

```bash
./build/release/ppc-lab disasm \
  --code ./code.bin \
  --base 0x10000000 \
  --count 32
```

A normal emulated function return exits with status `0`. Unsupported
instructions, memory faults, import traps, and instruction_limit stops return
distinct nonzero status codes.

## 6. Supply ABI state

Pass integer arguments or pointers in GPRs:

```bash
./build/release/ppc-lab call \
  --code ./code.bin \
  --entry 0x10001234 \
  --set r3=0x40010000 \
  --set r4=64
```

Pass floating-point values in FPRs:

```bash
./build/release/ppc-lab call \
  --code ./code.bin \
  --entry 0x10001234 \
  --set-f f1=0.5 \
  --set-f f2=2.0
```

For Classic CFM code, a transition vector can provide the entry point and TOC:

```bash
./build/release/ppc-lab call \
  --code ./code.bin \
  --data ./data.bin \
  --transition-vector 0x20005224
```

## 7. Initialize target memory

Write deterministic inputs before execution:

```bash
./build/release/ppc-lab call \
  --code ./code.bin \
  --entry 0x10001234 \
  --write-u32 0x40010000=0x12345678 \
  --write-f32 0x40010004=0.25
```

Writes must land in writable mapped target/heap/data memory.

## 8. Bind only required imports

If execution reaches an imported function, PPC Lab normally stops with an
import trap. Bind a known generic behavior only when the target needs it:

```bash
./build/release/ppc-lab call \
  --code ./code.bin \
  --entry 0x10001234 \
  --stub sin@0x30000014 \
  --stub blockmove@0x300001c8
```

Do not globally guess imports. Unknown imports remaining traps is useful
research information.

## 9. Capture deterministic output

```bash
./build/release/ppc-lab call \
  --code ./code.bin \
  --entry 0x10001234 \
  --dump 0x40010000:128 \
  --json /tmp/result.json
```

Inspect it:

```bash
python3 scripts/ppc_result_inspect.py /tmp/result.json
```

Compare the dump against a reference byte file:

```bash
python3 scripts/compare_ppc_dump.py \
  --ppc /tmp/result.json \
  --reference /tmp/reference.bin
```

## 10. Turn the experiment into a profile

Once an invocation answers a recurring research question, do not leave it in
shell history. Put its addresses, bindings, expected fingerprints, and command
under `profiles/<target>/`.

If the target is redistributable ELF, the profile can simply point to it. For
commercial/proprietary input, keep the bytes external and accept a path through
an environment variable or script argument.

See `docs/ADDING_A_TARGET.md`.

## 11. What to do when execution stops

- `returned`: capture outputs and compare behavior.
- `unsupported_instruction`: implement that opcode only if the target needs it,
  then add a synthetic test.
- `memory_fault`: verify mappings, pointers, relocation assumptions, stack, and
  writable regions.
- `import_trap`: identify the imported function and add the smallest reusable
  stub if required.
- `instruction_limit`: inspect trace/control flow before simply raising the
  limit.
- `invalid_configuration`: fix the call setup or move a harness-owned range that
  overlaps target memory.
- `backend_error`: try the built-in backend and inspect backend-specific setup.

The intended workflow is incremental: **target question -> deterministic call
-> smallest missing capability -> regression test -> continue target research**.
