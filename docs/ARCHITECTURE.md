# Architecture

PPC Lab is organized so that improving one research target improves the
platform without making future targets inherit that project's assumptions.

## Layer 1 — deterministic PPC machine model

Core components provide:

- PPC32 big-endian CPU state;
- mapped memory with explicit R/W/X permissions;
- deterministic register/memory initialization;
- execution stop reasons;
- built-in interpreter;
- optional alternative execution backends;
- trace hooks and instruction limits.

This layer knows nothing about PEF, Mach-O, ELF, ReBirth, firmware products, or
operating-system APIs.

## Layer 2 — binary intake

Native loaders translate file-format structures into a common research image:

```text
binary container
      │
      ▼
 UniversalImageLoader (detect / common v1 boundary)
      │
      ├── Elf32Loader
      ├── MachOLoader
      └── PefLoader
             │
             ▼
 mapped Memory + ImageSymbol[] + entry + relocation results
```

Raw `--code`/`--data` remains available as an escape hatch for custom formats
or already-relocated sections.

Loaders own **format mechanics**: bounds checking, section/segment layout,
rebasing, standard relocations, symbols, and format-provided entry metadata.
They do not own a target's runtime environment.

## Layer 3 — CallHarness

`CallHarness` provides a uniform isolated-function environment over every image
source:

- exactly one image source (`--image` auto-detected, explicit native format, or raw);
- deterministic heap and stack;
- return trampoline;
- entry selection;
- optional CFM transition-vector setup;
- GPR/FPR assignments;
- initial memory writes;
- import address range and runtime stub bindings;
- execution configuration.

Entry selection is intentionally explicit and predictable:

```text
explicit transition vector
        ↓
explicit numeric entry
        ↓
explicit entry symbol
        ↓
loader-discovered entry
```

## Layer 4 — target/runtime profile

A profile may define:

- exact target/version hashes;
- import address bindings;
- symbol maps derived during research;
- object/buffer addresses;
- ABI/runtime assumptions;
- fixture inputs;
- known instruction counts/state hashes;
- invocation scripts.

This is where application-specific knowledge belongs.

## Symbol model

All native loaders publish the shared `ImageSymbol` representation. External
resolution uses `SymbolBinding { name, address }`. This keeps target-specific
linking policy out of the parsers and allows future debugger/decompiler tooling
to consume symbols without knowing which container produced them.

## Runtime stubs versus symbol bindings

These are deliberately separate:

- `--bind name=address` answers **where does this imported symbol resolve?**
- `--stub behavior@address` answers **what should happen when PPC execution
  calls this address?**

That means a profile can model a target import map without forcing PPC Lab to
pretend it has faithfully implemented the original library.

## Backends

The built-in interpreter is the dependency-free reference backend. Unicorn is
an optional acceleration/cross-check backend. Backends consume the same mapped
memory and prepared CPU state; they should not bypass loader or call-harness
semantics.

## Determinism

PPC Lab defaults are intentionally stable:

- image base: `0x10000000` where rebasing/layout is needed;
- raw data base: `0x20000000`;
- heap base: `0x40000000`;
- stack base: `0x70000000`;
- harness return trampoline: `0x7fff0000`.

Changing addresses is supported, but recorded experiments should state the
non-default values.

## Failure is evidence

The platform distinguishes unsupported instructions, memory faults, unresolved
imports, instruction limits, and normal return. Loader errors likewise reject
unsupported relocation/container behavior instead of silently guessing. A
failure should identify the next piece of research infrastructure required.

## Long-term invariant

Generic areas (`include/`, `src/`, `tools/`, generic `scripts/`, synthetic
`tests/`) must not acquire target-specific addresses or proprietary code. The
repository invariant test enforces known extraction sentinels so accidental
regression is caught in CI.

## v0.4 research/evidence layer

v0.4 adds a layer **above** binary intake and `CallHarness`; it does not move
research policy into the CPU core:

```text
native loader -> CallHarness -> backend
     |              |            |
     |              +-> snapshot + symbol-aware trace
     |                           |
     +-> metadata JSON           v
                        experiment / differential tools
                                  |
                                  v
                        decompiler-neutral evidence
                                  |
                    +-------------+-------------+
                    v             v             v
                  Ghidra          IDA       Binary Ninja
```

Runtime personality JSON maps **names to reusable behaviors**. The runner
allocates deterministic import identities and translates the profile into normal
`--bind`/`--stub` arguments. This preserves the core rule that addresses and
runtime assumptions are policy rather than loader behavior.

Snapshots and evidence formats are intentionally separate from backend internals.
A future backend can participate if it honors `ExecutionBackend` and produces the
same architectural state.

## v1 public package boundary

The source-tree API and installed API are the same public headers under `include/ppclab/ppc/`. CMake exports the static core as `PPCLab::core`; a downstream project can use `find_package(PPCLab 1.0 CONFIG REQUIRED)` after installation. The install-contract test compiles an external consumer against that exported target, so accidental source-tree-only include/link assumptions are release-blocking failures.

The CLI version is sourced from the CMake project version. `capabilities --json` is the machine-readable discovery boundary for automation; `doctor` is the human/runtime sanity boundary.
