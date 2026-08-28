# CLI reference

Executable name: `ppc-lab`.

## v1 discovery commands

```bash
ppc-lab doctor
ppc-lab capabilities [--json]
ppc-lab analyze FILE [--json] [--symbols]
```

`doctor` runs the built-in execution microtests and, when compiled in, the Unicorn microtests. `capabilities --json` emits the stable `ppc-lab-capabilities-v1` discovery schema. `analyze` auto-detects a supported native container and summarizes format, entry, and symbol state without executing target code.

## `selftest`

```bash
ppc-lab selftest [--backend auto|builtin|unicorn]
```

Runs small deterministic CPU/memory/ABI execution tests.

## `image-info`

```bash
ppc-lab image-info FILE
```

Auto-detects ELF32 PPC, PPC32 Mach-O, or PEF/CFM and prints safe container
metadata without executing it.

Format-specific aliases:

```bash
ppc-lab elf-info FILE
ppc-lab macho-info FILE
ppc-lab pef-info FILE
```

The explicit form is useful when a script expects one exact format.

## `symbols`

```bash
ppc-lab symbols FILE
```

Auto-detects the native image and prints symbols exposed by its symbol/export
metadata. Runtime addresses are available after loading/rebasing; inspection
metadata may contain original/container-relative values depending on format.

## `disasm`

```bash
ppc-lab disasm (--image FILE | --code FILE | --elf FILE | --macho FILE | --pef FILE) \
  [--base ADDRESS] \
  [--image-base ADDRESS] \
  [--start ADDRESS] \
  [--count N] \
  [--bind NAME=ADDRESS]
```

Exactly one input is required.

- `--base` sets raw-code base; default `0x10000000`.
- `--image-base` sets the deterministic rebase/layout base for native formats
  that need one; default `0x10000000`.
- `--start` overrides the first disassembly address.
- `--count` is instruction count, not bytes.
- `--bind` supplies a symbol address required while loading/relocating an image.

If `--start` is absent, PPC Lab uses the native entry where one exists and then
falls back to the first executable mapped region.

## `call`

```bash
ppc-lab call|run (--image FILE | --code FILE | --elf FILE | --macho FILE | --pef FILE) [--data FILE] \
  [--entry ADDRESS | --entry-symbol NAME | --transition-vector ADDRESS] \
  [--image-base ADDRESS] [--bind NAME=ADDRESS] \
  [--backend auto|builtin|unicorn] \
  [--code-base ADDRESS] [--data-base ADDRESS] [--data-map-size SIZE] \
  [--heap-base ADDRESS] [--heap-size SIZE] \
  [--stack-base ADDRESS] [--stack-size SIZE] \
  [--import-base ADDRESS] [--import-size SIZE] \
  [--return ADDRESS] [--toc ADDRESS] \
  [--max-instructions N] \
  [--set rN=VALUE] [--set-f fN=VALUE] \
  [--write-u32 ADDRESS=VALUE] [--write-f32 ADDRESS=VALUE] \
  [--stub KIND@ADDRESS] \
  [--dump ADDRESS:SIZE] \
  [--trace] [--trace-range START:END] \
  [--json FILE] [--snapshot FILE]
```

### Inputs

Exactly one primary input is required:

- `--image FILE` — auto-detect a supported native ELF32 PPC, Mach-O PPC32, or PEF/CFM image;
- `--code FILE` — raw PPC bytes;
- `--elf FILE` — ELF32 big-endian PowerPC;
- `--macho FILE` — PPC32 big-endian Mach-O;
- `--pef FILE` — PowerPC PEF/CFM.

`--data FILE` is a raw companion map intended primarily for raw-code research.

### Entry selection

- `--transition-vector ADDRESS` reads a Classic CFM-style transition vector and
  establishes entry/TOC state;
- `--entry ADDRESS` selects a numeric entry;
- `--entry-symbol NAME` selects a loaded native symbol;
- otherwise PPC Lab uses the loader-discovered entry.

### Native image layout/linking

- `--image-base ADDRESS` controls ET_DYN/ET_REL, MH_DYLIB/MH_OBJECT, and PEF
  deterministic placement;
- `--bind NAME=ADDRESS` resolves one imported/undefined symbol during image
  relocation. Repeat as needed.

### Raw image defaults

```text
code base      0x10000000
data base      0x20000000
data map size  0x00200000
heap base      0x40000000
heap size      0x00200000
stack base     0x70000000
stack size     0x00100000
return address 0x7fff0000
```

### Register initialization

```bash
--set r3=0x40010000
--set r4=64
--set-f f1=0.5
--toc 0x20008000
```

Assignments may be repeated. Integer values accept decimal or `0x` hexadecimal.

### Initial memory writes

```bash
--write-u32 0x40010000=0x12345678
--write-f32 0x40010010=0.5
```

Writes occur after image/auxiliary maps exist and before execution.

### Runtime stubs

Syntax:

```bash
--stub KIND@ADDRESS
```

Current reusable kinds:

```text
pow
cos
sqrt
sin
exp
fabs
floor
ceil
blockmove
memcpy
memmove
memset
bzero
```

A stub binding is an execution aid, not proof of bit-exact parity with the
original runtime.

### System calls and traps

The PPC `sc` instruction is an architectural boundary, not an operating-system
emulation promise. PPC Lab exposes it explicitly. The v1 deterministic syscall
binding convention uses `r0` as the syscall selector and `r3` as the fixed return
value:

```bash
--syscall-return 4=0
--syscall-return 0x66=0xffffffff
--default-syscall-return 0
```

Bindings may be repeated. If `sc` has no exact/default binding, execution stops
with `stop=system_call`. `tw`/`twi` stop with `stop=trap` when their condition is
true. `--ignore-traps` advances past matching trap instructions for experiments
that intentionally do not model the exception path. It does **not** globally
disable memory faults, imports, or system calls.

The `r0`/`r3` convention is useful for common 32-bit Unix-style PPC research but
is not an architectural definition of every operating system ABI. Target
personality scripts should own ABI-specific policy.

### Tracing

```bash
--trace
--trace-range 0x10001200:0x10001400
```

`--trace` enables instruction trace output. For native images, loaded symbols are carried into the execution backend and trace lines are annotated with the nearest matching symbol and offset. `--trace-range` restricts trace reporting to an inclusive address interval while execution can continue outside it.

### Dumps and JSON

```bash
--dump 0x40010000:128
--json /tmp/result.json
--snapshot /tmp/state.json
```

Each dump reports bytes plus FNV-1a64. `--json` preserves the compact result schema. `--snapshot` emits the richer `ppc-lab-snapshot-v1` state checkpoint documented in [`SNAPSHOTS.md`](SNAPSHOTS.md).

## Backend selection

- `builtin` — dependency-free PPC32 big-endian interpreter;
- `unicorn` — optional Unicorn backend if compiled in;
- `auto` — Unicorn when available, otherwise builtin.

For long-lived regression fixtures, explicitly naming `builtin` avoids backend
selection changes.

## Stop reasons and process exit behavior

Normal return exits successfully. Execution errors map to nonzero exit status so
shell/CI scripts can treat an incomplete experiment as failure. The CLI prints
`stop=...`, `instructions=...`, final PC/register state, and an explanatory
message when available.

Current execution stop categories include normal return, unsupported
instruction, unmapped/protection memory fault, trapped unresolved import,
architectural trap, system call, instruction-limit stop, backend failure, and
setup/load failure. Treat the printed stop reason as the stable research signal;
scripts should not depend on undocumented prose.

Current process exit codes are:

```text
0  normal return / successful non-execution command
1  argument, setup, load, or generic command failure
2  unsupported instruction
3  memory fault
4  unresolved import trap
5  instruction limit
6  backend failure
7  other execution stop
8  architectural trap (`tw`/`twi`)
9  unbound system call (`sc`)
```

## `metadata`

```bash
ppc-lab metadata FILE [--image-base ADDRESS] [--bind NAME=ADDRESS]
```

Loads a supported native image through the same loader used by `call` and emits
`ppc-lab-metadata-v1` JSON containing normalized format, mapped entry, regions,
permissions, and symbols. This is the preferred machine-readable intake
interface for decompiler and automation tooling.

## v0.4 research scripts

```bash
python3 scripts/ppc_runtime_call.py --runtime RUNTIME.json --image IMAGE -- [call options]
python3 scripts/ppc_trace_capture.py --json TRACE.json -- [call options]
python3 scripts/ppc_snapshot_diff.py LEFT.json RIGHT.json [--ignore-backend]
python3 scripts/ppc_lab_batch.py MANIFEST.json --out DIRECTORY
python3 scripts/ppc_differential.py MANIFEST.json
python3 scripts/ppc_evidence_pack.py --metadata META.json [--snapshot SNAP.json] [--trace TRACE.json] --json OUT.json
```

See `RUNTIMES.md`, `SNAPSHOTS.md`, `EXPERIMENTS.md`, and
`DECOMPILER_INTEGRATION.md` for the corresponding schemas and workflows.
