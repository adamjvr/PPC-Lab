# Quick start

## 1. Build and verify

macOS/Linux:

```bash
./Tools/verify.command
```

The release binary is normally:

```bash
./build/release/ppc-lab
```

Sanity check:

```bash
./build/release/ppc-lab selftest --backend builtin
```

## 2. Identify a native PPC image

```bash
./build/release/ppc-lab image-info /path/to/target
```

Supported v0.3 native intake:

- ELF32 big-endian PowerPC (`ET_EXEC`, `ET_DYN`, `ET_REL`);
- 32-bit big-endian PowerPC Mach-O, thin or fat;
- PowerPC PEF/CFM.

If the target is not a native supported container but you already have raw
relocated code, use `--code` as before.

## 3. See symbols when available

```bash
./build/release/ppc-lab symbols /path/to/target
```

For relocatable objects this is often the fastest way to choose a function for
an isolated experiment.

## 4. Disassemble a small region

```bash
./build/release/ppc-lab disasm --elf target.elf --count 32
./build/release/ppc-lab disasm --macho target.macho --count 32
./build/release/ppc-lab disasm --pef target.pef --count 32
```

Override the start address when useful:

```bash
./build/release/ppc-lab disasm --elf target.elf --start 0x00104560 --count 64
```

## 5. Execute an entry or function

Native default entry:

```bash
./build/release/ppc-lab call --elf target.elf --backend builtin
```

Named function in a relocatable/shared image:

```bash
./build/release/ppc-lab call \
  --elf module.o \
  --image-base 0x12000000 \
  --entry-symbol process \
  --set r3=5
```

Numeric function entry:

```bash
./build/release/ppc-lab call \
  --macho target.macho \
  --entry 0x00104560 \
  --set r3=0x40010000
```

PEF default main:

```bash
./build/release/ppc-lab call \
  --pef application.pef \
  --image-base 0x11000000
```

## 6. Bind an unresolved external only when execution needs it

If relocation/loading reports a missing symbol:

```bash
./build/release/ppc-lab call \
  --elf module.o \
  --entry-symbol process \
  --bind memcpy=0x30000100
```

If that address should also behave like one of PPC Lab's reusable runtime
stubs:

```bash
--bind memcpy=0x30000100 --stub blockmove@0x30000100
```

Do not pre-stub everything. Let execution tell you what is actually required.

## 7. Capture deterministic evidence

```bash
./build/release/ppc-lab call \
  --elf target.elf \
  --entry 0x00104560 \
  --set r3=5 \
  --dump 0x40010000:128 \
  --trace-range 0x00104560:0x00104680 \
  --json /tmp/ppc-result.json
```

Inspect the result:

```bash
python3 scripts/ppc_result_inspect.py /tmp/ppc-result.json
```

Compare two deterministic dumps/results with the scripts under `scripts/`.

## 8. Turn a successful experiment into a profile

Once the experiment answers a useful research question, put only the reusable
metadata/script/expected hashes under `profiles/<target>/`. Keep proprietary
binary bytes external.

See [`ADDING_A_TARGET.md`](ADDING_A_TARGET.md).
