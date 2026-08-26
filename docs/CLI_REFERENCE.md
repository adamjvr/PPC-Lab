# PPC Lab CLI reference

The current CLI has two commands: `selftest` and `call`.

```text
ppc-lab selftest [options]
ppc-lab call [options]
```

Run `ppc-lab` with no arguments to print the built-in usage text.

## `selftest`

```bash
ppc-lab selftest [--backend auto|builtin|unicorn]
```

Runs synthetic PPC CPU, memory, branch/call, floating-point, and ABI-oriented microtests against the selected execution backend.

Backend values:

- `builtin`: dependency-free PPC32-BE interpreter;
- `unicorn`: Unicorn backend; fails if unavailable in the build;
- `auto`: prefer Unicorn when available, otherwise use the built-in backend.

## `call`

Minimum direct call:

```bash
ppc-lab call --code FILE --entry ADDRESS
```

Minimum CFM transition-vector call:

```bash
ppc-lab call --code FILE --data FILE --transition-vector ADDRESS
```

Exactly one useful entry mechanism must be provided by the call configuration: a direct entry point or a transition vector.

## Image and address options

| Option | Meaning | Default |
|---|---|---:|
| `--code FILE` | Raw PPC code image. | required |
| `--data FILE` | Optional raw data image. | none |
| `--entry HEX` | Direct entry PC. | none |
| `--transition-vector HEX` | Read CFM entry/TOC from data memory. | none |
| `--toc HEX` | Explicit `r2`/TOC value for a direct call. | `0` unless otherwise set |
| `--code-base HEX` | Base address for code mapping. | `0x10000000` |
| `--data-base HEX` | Base address for data mapping. | `0x20000000` |
| `--data-map-size N` | Total mapped size for data image. | implementation default |
| `--heap-base HEX` | Base of deterministic heap/scratch mapping. | `0x40000000` |
| `--heap-size N` | Heap/scratch mapping size. | implementation default |
| `--stack-base HEX` | Base of deterministic stack mapping. | `0x70000000` |
| `--stack-size N` | Stack mapping size. | implementation default |
| `--import-base HEX` | Start of imported-function trap range. | `0x30000000` |
| `--import-size N` | Size of import trap range. | implementation default |
| `--return HEX` | Synthetic return address used to recognize a normal call return. | `0x7fff0000` |

Numbers accept decimal or `0x`-prefixed hexadecimal syntax.

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

Both options may be repeated.

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

The address belongs to the target, not to PPC Lab. This is deliberate: generic behavior stays in the core; target binding stays in the invocation/profile.

Unknown imported calls should normally remain trapped until their behavior is understood.

## Execution control

| Option | Meaning |
|---|---|
| `--backend auto|builtin|unicorn` | Select execution backend. |
| `--max-instructions N` | Stop after N emulated instructions. |
| `--trace` | Emit instruction trace. |
| `--trace-range START:END` | Restrict tracing to a PC range. |

An instruction limit is a safety/research guard. Raising it can be appropriate, but an unexpected limit stop often means control flow, imports, or initialization are wrong.

## Output and dumps

```bash
--dump ADDRESS:SIZE
```

May be repeated. PPC Lab prints bytes and an FNV-1a64 fingerprint for readable requested ranges.

```bash
--json FILE
```

Writes a `ppc-lab-result-v1` result document. See `docs/RESULT_FORMAT.md`.

## Stop reasons and process exit codes

| Exit | Stop reason | Meaning |
|---:|---|---|
| `0` | `returned` | Execution reached the synthetic return address normally. |
| `1` | CLI/argument/tool error | Invalid command-line usage or output-file error. |
| `2` | `unsupported-instruction` | Built-in/backend path cannot execute the current opcode. |
| `3` | `memory-fault` | Invalid/unmapped/forbidden memory access. |
| `4` | `import-trap` | Code called an unbound target import. |
| `5` | `instruction-limit` | Maximum instruction count reached. |
| `6` | `invalid-configuration` | Call/memory configuration is internally invalid. |
| `7` | `backend-error` | Requested backend unavailable or backend failed. |

Use these exit codes in scripts and CI instead of parsing human-readable output.

## Determinism notes

PPC Lab controls mapped bytes, register initialization, stub bindings, stack/heap regions, and stop conditions. Host transcendental math used by generic stubs can still differ from a historical target's original math library, so a successful call does not automatically imply bit-exact historical floating-point behavior.
