# PPC Lab architecture

## Goal

Provide a stable execution substrate for PowerPC reverse engineering that can survive many unrelated projects without turning into a monolithic emulator or a dependency of any one product.

```text
external target bytes
      |
loader / relocation tooling (profile-specific or future generic loaders)
      |
PPC Lab deterministic memory image
      |
+--------------------------------+
| CallHarness                    |
|  CPU/ABI initialization        |
|  map layout                    |
|  import bindings               |
|  return sentinel               |
+---------------+----------------+
                |
+---------------v----------------+
| ExecutionBackend               |
|  builtin-ppc32be               |
|  unicorn-ppc32be (optional)    |
+---------------+----------------+
                |
CPU state + stop reason + memory
                |
JSON / trace / differential tools
                |
project-specific conclusions
```

## Core invariants

1. **Target-neutrality.** No application's hard-coded addresses belong in the reusable core.
2. **Determinism.** Initial CPU/memory state and stop conditions must be controllable and reproducible.
3. **Fail on unknowns.** Unsupported instructions/imports/memory accesses are explicit stops, not silent approximations.
4. **Dependency-light baseline.** The built-in interpreter must remain usable without Unicorn or an emulated OS.
5. **Evidence over completeness.** Implement what real research targets need and regression-test it.
6. **Scriptability.** Headless CLI/JSON behavior is a first-class interface.

## Main components

### `CpuState`

Holds architectural state needed by the harness: GPRs, FPRs, PC, LR, CTR, CR, and related execution-visible state implemented by the backend.

### `Memory`

Owns deterministic mapped regions with read/write/execute permissions and explicit PPC big-endian accessors. The call harness uses separate conventional regions for code, data, imports, heap/scratch, stack, and return handling.

### `CallHarness`

Turns raw target bytes plus call configuration into one deterministic experiment. Responsibilities include loading images, mapping memory, applying register/memory initializers, resolving a direct entry or CFM transition vector, configuring the return sentinel, then invoking an execution backend.

### `ExecutionBackend`

Abstracts the instruction engine. PPC Lab currently provides:

- `builtin-ppc32be`: dependency-free interpreter with deliberately incremental ISA coverage;
- `unicorn-ppc32be`: optional wrapper around Unicorn when available.

The rest of PPC Lab should not need to know which backend actually executed the routine.

### Import traps and stubs

Imported target calls live in a configured address range. Unknown imports stop execution. Generic known behaviors such as `sin`, `sqrt`, or `blockmove` can be bound to **target-supplied addresses** at invocation time.

This split is critical:

```text
core:    "I know how a generic blockmove behaves."
profile: "this target's BlockMove entry is 0x300001c8."
```

### Result tooling

The CLI can capture register state, stop information, memory dumps, and FNV fingerprints into a small JSON result. Python helpers compare deterministic dumps against external/native/reference outputs.

## Hard boundaries

### Core owns

- CPU state;
- PPC big-endian memory semantics;
- execution backends;
- deterministic mappings;
- call setup;
- CFM transition-vector mechanics;
- generic import-stub behaviors;
- tracing and stop reasons;
- portable result formats.

### Profiles own

- target addresses;
- target TOC values;
- import-address bindings;
- symbols and routine names;
- known-good hashes/fingerprints;
- target-specific extraction/relocation instructions;
- provenance/legal notes for external bytes.

### External tooling may own

- PEF/CFM parsing and relocation;
- Mach-O/ELF loaders;
- firmware container extraction;
- Ghidra/IDA/Binary Ninja integration;
- real-PPC capture agents.

These can migrate into PPC Lab when repeated reuse justifies it, but the execution core does not need to wait for them.

## Default deterministic address model

The CLI exposes all of these values, but conventional defaults make simple fixtures cheap:

```text
code       0x10000000
 data      0x20000000
 imports   0x30000000
 heap      0x40000000
 stack     0x70000000
 return    0x7fff0000
```

These are harness conventions, not claims about a real target's original virtual memory map.

## CFM transition-vector support

Classic Mac CFM code commonly passes a transition vector rather than a raw function address. PPC Lab's call harness can derive the entry point and TOC/r2 setup from the supplied vector and prepare `r12` as expected by the modeled calling pattern.

CFM support here is a **call mechanism**, not a complete Classic Mac runtime.

## What PPC Lab intentionally is not

- a full Classic Mac OS emulator;
- a complete PowerPC ISA implementation;
- a console emulator;
- a hardware/electrical simulator;
- a magical automatic decompiler;
- a place to store proprietary binaries.

It is the small deterministic layer between static reverse engineering and behavioral evidence.

## Deliberate development model

Do not chase full ISA or OS coverage for its own sake. When a real target stops on opcode X or import Y:

1. verify the stop;
2. implement the smallest generally reusable capability;
3. add a synthetic regression;
4. rerun the target;
5. preserve useful target evidence in its profile;
6. return to the actual reverse-engineering project.
