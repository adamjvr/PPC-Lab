# PPC Lab CLI reference

PPC Lab v0.2.0 exposes four operational commands plus a version query:

```text
ppc-lab selftest [options]
ppc-lab elf-info FILE
ppc-lab disasm [options]
ppc-lab call [options]
ppc-lab --version
```

Run `ppc-lab` with no arguments to print the built-in usage text.

## `selftest`

```bash
ppc-lab selftest [--backend auto|builtin|unicorn]
```

Runs synthetic PPC CPU, memory, branch/call, floating-point, and ABI-oriented
microtests against the selected execution backend.

Backend values:

- `builtin`: dependency-free PPC32-BE interpreter;
- `unicorn`: Unicorn backend; fails if unavailable in the build;
- `auto`: prefer Unicorn when available, otherwise use the built-in backend.

## `elf-info`

```bash
ppc-lab elf-info FILE
```

Validates and summarizes a supported ELF32 PowerPC executable. It prints the
ELF entry point and every non-empty `PT_LOAD` segment with virtual/physical
address, file offset, file/memory size, alignment, and `R/W/X` flags.

This command does not execute target code.

Current accepted ELF contract: ELF32, big-endian, `EM_PPC`, `ET_EXEC`.
Unsupported classes/endianness/machines/types fail explicitly. See
[`ELF32.md`](ELF32.md).

## `disasm`

Raw code:

```bash
ppc-lab disasm --code FILE [--base HEX] [--start HEX] [--count N]
```

ELF code:

```bash
ppc-lab disasm --elf FILE [--start HEX] [--count N]
```

Options:

| Option | Meaning | Default |
|---|---|---:|
| `--code FILE` | Raw PPC32-BE instruction bytes. Mutually exclusive with `--elf`. | none |
| `--elf FILE` | Supported ELF32 PowerPC executable. Mutually exclusive with `--code`. | none |
| `--base HEX` | Mapping base for raw code. | `0x10000000` |
| `--start HEX` | First PC to decode. | raw base / ELF `e_entry` |
| `--count N` | Number of 4-byte instructions to decode. | `32` |

Output includes address, raw instruction word, and PPC Lab's decoded mnemonic.
Unknown encodings remain visible as raw `.long` values. This is intentionally a
lightweight view that shares the built-in execution decoder; use a full
decompiler/disassembler for broad static analysis.

## `call`

Raw direct call:

```bash
ppc-lab call --code FILE --entry ADDRESS
```

Raw CFM transition-vector call:

```bash
ppc-lab call --code FILE --data FILE --transition-vector ADDRESS
```

ELF call using the file's entry point:

```bash
ppc-lab call --elf FILE
```

ELF isolated-function call:

```bash
ppc-lab call --elf FILE --entry ADDRESS
```

Exactly one input image format is required: `--code` or `--elf`.

Entry precedence is:

1. `--transition-vector`;
2. explicit `--entry`;
3. ELF `e_entry`.

Raw images have no embedded entry point, so raw mode requires `--entry` or
`--transition-vector`.

## Image and address options

| Option | Meaning | Default |
|---|---|---:|
| `--code FILE` | Raw PPC32-BE code image. Mutually exclusive with `--elf`. | none |
| `--elf FILE` | ELF32 big-endian `EM_PPC` `ET_EXEC`; maps `PT_LOAD` segments. | none |
| `--data FILE` | Optional extra raw data image. | none |
| `--entry HEX` | Direct entry PC; overrides ELF `e_entry`. | ELF entry / none for raw |
| `--transition-vector HEX` | Read CFM entry/TOC from mapped memory. | none |
| `--toc HEX` | Explicit `r2`/TOC value for a direct call. | `0` unless otherwise set |
| `--code-base HEX` | Base address for raw code mapping. Ignored by ELF segment addresses. | `0x10000000` |
| `--data-base HEX` | Base address for optional raw data mapping. | `0x20000000` |
| `--data-map-size N` | Total mapped size for an optional raw data image. | implementation default |
| `--heap-base HEX` | Base of deterministic heap/scratch mapping. | `0x40000000` |
| `--heap-size N` | Heap/scratch mapping size. | implementation default |
| `--stack-base HEX` | Base of deterministic stack mapping. | `0x70000000` |
| `--stack-size N` | Stack mapping size. | implementation default |
| `--import-base HEX` | Start of imported-function trap range. | `0x30000000` |
| `--import-size N` | Size of import trap range. | implementation default |
| `--return HEX` | Synthetic return address used to recognize a normal function return. | `0x7fff0000` |

Numbers accept decimal or `0x`-prefixed hexadecimal syntax.

ELF mode skips the synthetic default data mapping unless `--data FILE` is
explicitly supplied. ELF writable `PT_LOAD` segments are normally the target's
data/BSS image. Harness-owned import/heap/stack ranges must not overlap ELF
segments; change their bases when necessary.

## CPU initialization

### General-purpose registers

```bash
--set rN=VALUE
```

May be repeated. `N` is `0..31`.

Example:

```bash
--set r3=0x40010000 --set r4=256
```

### Floating-point registers

```bash
--set-f fN=VALUE
```

May be repeated. `N` is `0..31`.

Example:

```bash
--set-f f1=0.5 --set-f f2=-1.25
```

## Memory initialization

Write a big-endian 32-bit integer:

```bash
--write-u32 ADDRESS=VALUE
```

Write a 32-bit floating-point value:

```bash
--write-f32 ADDRESS=VALUE
```

Both options may be repeated and must land in writable mapped memory.

## Import stubs

```bash
--stub KIND@ADDRESS
```

May be repeated. Built-in kinds:

- `pow`
- `cos`
- `sqrt`
- `sin`
- `exp`
- `blockmove`

The address belongs to the target, not to PPC Lab. Generic behavior stays in
the core; target binding stays in the invocation/profile.

Unknown imported calls should normally remain trapped until their behavior is
understood.

## Execution control

| Option | Meaning |
|---|---|
| `--backend auto|builtin|unicorn` | Select execution backend. |
| `--max-instructions N` | Stop after N emulated instructions. |
| `--trace` | Emit instruction trace. |
| `--trace-range START:END` | Restrict tracing to an inclusive PC range. |

An instruction limit is a safety/research guard. Raising it can be appropriate,
but an unexpected limit stop often means control flow, imports, or
initialization are wrong.

## Output and dumps

```bash
--dump ADDRESS:SIZE
```

May be repeated. PPC Lab prints bytes and an FNV-1a64 fingerprint for readable
requested ranges.

```bash
--json FILE
```

Writes a `ppc-lab-result-v1` result document. See
[`RESULT_FORMAT.md`](RESULT_FORMAT.md).

## Stop reasons and process exit codes

| Exit | Stop reason | Meaning |
|---:|---|---|
| `0` | `returned` | Execution reached the synthetic return address normally. |
| `1` | CLI/argument/tool/input-format error | Invalid usage, unsupported ELF format, disassembly input, or output-file error. |
| `2` | `unsupported_instruction` | Built-in/backend path cannot execute the current opcode. |
| `3` | `memory_fault` | Invalid/unmapped/forbidden memory access. |
| `4` | `import_trap` | Code called an unbound target import. |
| `5` | `instruction_limit` | Maximum instruction count reached. |
| `6` | `invalid_configuration` | Call/memory configuration is internally invalid, including mapping overlap. |
| `7` | `backend_error` | Requested backend unavailable or backend failed. |

Use these exit codes in scripts and CI instead of parsing human-readable output.

## Determinism notes

PPC Lab controls mapped bytes, register initialization, stub bindings,
stack/heap regions, and stop conditions. Host transcendental math used by
generic stubs can still differ from a historical target's original math
library, so a successful call does not automatically imply bit-exact historical
floating-point behavior.
